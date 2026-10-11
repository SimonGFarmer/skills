#!/usr/bin/env python3
"""One bounded Planetary Computer STAC page per invocation; no asset downloads."""
import argparse
import copy
import datetime as dt
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SEARCH = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
DATA = "https://planetarycomputer.microsoft.com/api/data/v1/item/bbox/"
COLLECTIONS = {"landsat-c2-l2", "sentinel-2-l2a"}
MAX_BYTES = 8 * 1024 * 1024
SAS_KEYS = {"sig", "st", "se", "sp", "sv", "sr", "spr", "sip", "skoid",
            "sktid", "skt", "ske", "sks", "skv", "ses", "si"}


def number(value):
    if isinstance(value, bool):
        raise ValueError("Boolean values are not numeric coordinates")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Coordinates and limits must be finite")
    return result


def integer(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{label} must be an integer from {low} through {high}")
    return value


def validate_query(query):
    if not isinstance(query, dict) or set(query) != {"collections", "bbox", "datetime", "limit", "query"}:
        raise ValueError("Invalid saved query structure")
    collections = query["collections"]
    if not isinstance(collections, list) or len(collections) != 1 or not isinstance(collections[0], str) or collections[0] not in COLLECTIONS:
        raise ValueError("Choose landsat-c2-l2 or sentinel-2-l2a")
    box = query["bbox"]
    if not isinstance(box, list) or len(box) != 4:
        raise ValueError("bbox must contain west south east north")
    west, south, east, north = map(number, box)
    if not (-180 <= west < east <= 180 and -75 <= south < north <= 75):
        raise ValueError("Invalid bbox; latitude is bounded to ±75 degrees; no antimeridian crossing")
    if east - west > 2.000000001 or north - south > 2.000000001:
        raise ValueError("bbox must be no more than 2 degrees wide/high")
    interval = query["datetime"]
    if not isinstance(interval, str):
        raise ValueError("Invalid acquisition interval")
    try:
        start_text, end_text = interval.split("/")
        if not start_text.endswith("T00:00:00Z") or not end_text.endswith("T23:59:59Z"):
            raise ValueError()
        start = dt.date.fromisoformat(start_text[:10])
        end = dt.date.fromisoformat(end_text[:10])
        if start.isoformat() + "T00:00:00Z" != start_text or end.isoformat() + "T23:59:59Z" != end_text:
            raise ValueError()
        if not 0 <= (end - start).days <= 365:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("Use an ordered interval of at most 366 acquisition days") from None
    limit = integer(query["limit"], 1, 40, "Page size")
    cloud_query = query["query"]
    if not isinstance(cloud_query, dict) or set(cloud_query) != {"eo:cloud_cover"}:
        raise ValueError("Invalid cloud filter")
    cloud_op = cloud_query["eo:cloud_cover"]
    if not isinstance(cloud_op, dict) or set(cloud_op) != {"lte"}:
        raise ValueError("Invalid cloud filter")
    cloud = number(cloud_op["lte"])
    if not 0 <= cloud <= 100:
        raise ValueError("Cloud threshold must be 0–100 percent")
    return {"collections": collections[:], "bbox": [west, south, east, north],
            "datetime": interval, "limit": limit, "query": {"eo:cloud_cover": {"lte": cloud}}}


def make_query(collection, bbox, start, end, cloud=30, limit=20):
    return validate_query({"collections": [collection], "bbox": list(bbox),
                           "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
                           "limit": limit, "query": {"eo:cloud_cover": {"lte": cloud}}})


def fixed_search_link(href):
    if not isinstance(href, str):
        raise ValueError("Invalid continuation link")
    parsed = urllib.parse.urlsplit(href)
    if (parsed.scheme, parsed.netloc, parsed.path) != ("https", "planetarycomputer.microsoft.com", "/api/stac/v1/search") or parsed.fragment:
        raise ValueError("Continuation must use the fixed official STAC search endpoint")
    return parsed


def next_token(links):
    candidates = [link for link in links if isinstance(link, dict) and link.get("rel") == "next"]
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError("Ambiguous STAC continuation")
    link = candidates[0]
    parsed = fixed_search_link(link.get("href"))
    method = link.get("method", "GET")
    if not isinstance(method, str):
        raise ValueError("Invalid STAC continuation method")
    method = method.upper()
    if method not in {"GET", "POST"}:
        raise ValueError("Unsupported STAC continuation method")
    url_tokens = urllib.parse.parse_qs(parsed.query).get("token", [])
    body = link.get("body", {})
    if not isinstance(body, dict):
        raise ValueError("Invalid continuation body")
    token = body.get("token") if method == "POST" else (url_tokens[0] if len(url_tokens) == 1 else None)
    if not isinstance(token, str) or not token or len(token) > 8192:
        raise ValueError("Unsupported or missing pagination token; narrow the search")
    return token


def redact_sas(value):
    if isinstance(value, dict):
        return {key: redact_sas(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_sas(item) for item in value]
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        parts = urllib.parse.urlsplit(value)
        pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        if any(key.lower() in SAS_KEYS for key, _ in pairs):
            safe = [(key, item) for key, item in pairs if key.lower() not in SAS_KEYS]
            return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(safe)))
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        raise ValueError("Unexpected redirect from the fixed STAC endpoint")


def fetch_page(query, token=None, timeout=30, max_bytes=MAX_BYTES, opener=None):
    query = validate_query(query)
    integer(timeout, 1, 30, "Timeout seconds")
    integer(max_bytes, 1024, MAX_BYTES, "Response byte limit")
    payload = copy.deepcopy(query)
    if token is not None:
        if not isinstance(token, str) or not token or len(token) > 8192:
            raise ValueError("Invalid pagination token")
        payload["token"] = token
    request = urllib.request.Request(SEARCH, data=json.dumps(payload, allow_nan=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "Accept": "application/geo+json, application/json",
                                              "User-Agent": "satellite-stac-data/1.0"}, method="POST")
    opener = opener or urllib.request.build_opener(NoRedirect())
    deadline = time.monotonic() + timeout
    with opener.open(request, timeout=timeout) as response:
        declared = response.headers.get("Content-Length")
        if declared is not None and int(declared) > max_bytes:
            raise ValueError("STAC response exceeds the byte limit")
        data = bytearray()
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError("STAC response deadline exceeded")
            chunk = response.read(min(65536, max_bytes + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > max_bytes:
                raise ValueError("STAC response exceeds the byte limit")
    if time.monotonic() > deadline:
        raise TimeoutError("STAC response deadline exceeded")
    result = json.loads(data)
    if not isinstance(result, dict) or result.get("type") != "FeatureCollection":
        raise ValueError("Expected a STAC FeatureCollection")
    if not isinstance(result.get("features"), list) or not isinstance(result.get("links", []), list):
        raise ValueError("Invalid STAC page structure")
    if len(result["features"]) > query["limit"]:
        raise ValueError("STAC server exceeded the requested page size")
    for item in result["features"]:
        if not isinstance(item, dict) or item.get("type") != "Feature" or item.get("collection") != query["collections"][0] or not isinstance(item.get("properties"), dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
            raise ValueError("Invalid STAC item")
        timestamp = item["properties"].get("datetime")
        try:
            if not isinstance(timestamp, str):
                raise ValueError()
            acquired = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if acquired.tzinfo is None or acquired.utcoffset() != dt.timedelta(0):
                raise ValueError()
        except ValueError:
            raise ValueError("Expected a valid UTC acquisition datetime") from None
        if not isinstance(item.get("assets", {}), dict) or not isinstance(item.get("links", []), list):
            raise ValueError("Invalid STAC asset/link metadata")
        if any(not isinstance(asset, dict) for asset in item.get("assets", {}).values()):
            raise ValueError("Invalid STAC asset metadata")
    return result


def bbox_preview(item, bbox, size=512):
    """Build a display URL only; never fetch this URL or any asset."""
    integer(size, 64, 1024, "Preview size")
    href = item.get("assets", {}).get("tilejson", {}).get("href")
    if not isinstance(href, str):
        return None
    base = urllib.parse.urlsplit(redact_sas(href))
    if (base.scheme, base.netloc, base.path) != ("https", "planetarycomputer.microsoft.com", "/api/data/v1/item/tilejson.json"):
        return None
    pairs = urllib.parse.parse_qsl(base.query, keep_blank_values=True)
    params = dict(pairs)
    if params.get("collection") != item.get("collection") or params.get("item") != item.get("id"):
        return None
    replaced = {"coord_crs", "dst_crs", "resampling", "reproject", "return_mask"}
    pairs = [(key, value) for key, value in pairs if key not in replaced]
    pairs.extend([("coord_crs", "EPSG:4326"), ("dst_crs", "EPSG:4326"), ("resampling", "nearest"),
                  ("reproject", "nearest"), ("return_mask", "true")])
    coords = ",".join(format(number(value), ".12g") for value in bbox)
    return f"{DATA}{coords}/{size}x{size}.png?{urllib.parse.urlencode(pairs)}"


def summarize(item, bbox):
    cloud = item["properties"].get("eo:cloud_cover")
    if isinstance(cloud, bool) or not isinstance(cloud, (int, float)) or not math.isfinite(cloud) or not 0 <= cloud <= 100:
        cloud = None
    return {"id": item["id"], "collection": item["collection"],
            "datetime": item["properties"].get("datetime"), "platform": item["properties"].get("platform"),
            "cloud_cover": cloud, "rendered_preview": item.get("assets", {}).get("rendered_preview", {}).get("href"),
            "bbox_preview": bbox_preview(item, bbox)}


def package_page(page, query, pages_fetched=1, page_limit=3):
    query = validate_query(query)
    integer(page_limit, 1, 5, "Page budget")
    integer(pages_fetched, 1, page_limit, "Pages fetched")
    token = next_token(page.get("links", []))
    clean = redact_sas(page)
    return {"query": query, "retrieved_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "pages_fetched": pages_fetched, "page_limit": page_limit,
            "has_more": token is not None, "page_budget_exhausted": token is not None and pages_fetched >= page_limit,
            "continuation": {"query": query, "token": token, "pages_fetched": pages_fetched,
                             "page_limit": page_limit} if token is not None and pages_fetched < page_limit else None,
            "summary": [summarize(item, query["bbox"]) for item in clean["features"]], "stac": clean}


def load_continuation(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Saved search exceeds the byte limit")
    saved = json.loads(data)
    continuation = saved.get("continuation") if isinstance(saved, dict) else None
    if not isinstance(continuation, dict) or set(continuation) != {"query", "token", "pages_fetched", "page_limit"}:
        raise ValueError("No usable continuation; inspect has_more and page_budget_exhausted")
    query = validate_query(continuation["query"])
    budget = integer(continuation["page_limit"], 1, 5, "Page budget")
    count = integer(continuation["pages_fetched"], 1, budget, "Pages fetched")
    token = continuation["token"]
    if count >= budget or not isinstance(token, str) or not token or len(token) > 8192:
        raise ValueError("Invalid or exhausted continuation")
    return query, token, count + 1, budget


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection", choices=sorted(COLLECTIONS))
    parser.add_argument("--bbox", type=float, nargs=4, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--cloud", type=float)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--page-limit", type=int)
    parser.add_argument("--continue-from")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    parser.add_argument("--output", help="New JSON file; existing files are never overwritten")
    args = parser.parse_args(argv)
    try:
        if args.continue_from:
            if any(value is not None for value in [args.collection, args.bbox, args.start, args.end, args.cloud, args.limit, args.page_limit]):
                raise ValueError("Continuation reuses its saved bounds; do not combine it with new search parameters")
            query, token, count, budget = load_continuation(args.continue_from)
        else:
            if any(value is None for value in [args.collection, args.bbox, args.start, args.end]):
                raise ValueError("A new search requires collection, bbox, start and end")
            query = make_query(args.collection, args.bbox, args.start, args.end,
                               30 if args.cloud is None else args.cloud, 20 if args.limit is None else args.limit)
            token, count, budget = None, 1, 3 if args.page_limit is None else args.page_limit
            integer(budget, 1, 5, "Page budget")
        page = fetch_page(query, token, args.timeout, args.max_bytes)
        output = package_page(page, query, count, budget)
        encoded = json.dumps(output, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.output:
            with Path(args.output).open("x", encoding="utf-8") as stream:
                stream.write(encoded)
        else:
            print(encoded, end="")
        return 0
    except urllib.error.HTTPError as error:
        retry = error.headers.get("Retry-After") if error.headers else None
        parser.exit(1, f"STAC HTTP {error.code}." + (f" Retry-After: {retry}." if retry else "") + " No automatic retry.\n")
    except (ValueError, TypeError, KeyError, OSError, TimeoutError) as error:
        parser.exit(1, f"Search failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
