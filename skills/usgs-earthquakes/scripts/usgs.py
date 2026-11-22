#!/usr/bin/env python3
"""Bounded public USGS catalog/feed access and exact product downloads."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import http.client
import io
import json
import math
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = "https://earthquake.usgs.gov"
SERVICE = ROOT + "/fdsnws/event/1/"
JSON_CAP = 8_000_000


class DataError(Exception):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value):
    # Require an explicit timezone for reproducible command-line queries.
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise DataError("Use an ISO timestamp with timezone, e.g. 2019-07-06T00:00:00Z") from exc
    if parsed.tzinfo is None:
        raise DataError("Timestamp requires Z or an explicit UTC offset")
    return parsed.astimezone(timezone.utc)


def epoch_utc(value):
    if value is None:
        return None
    number = numeric(value)
    if number is None:
        raise DataError("Invalid epoch milliseconds")
    try:
        return datetime.fromtimestamp(number / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError) as exc:
        raise DataError("Epoch milliseconds outside supported timestamp range") from exc


def numeric(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise DataError("Boolean in a numeric measurement")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DataError("Invalid numeric measurement") from exc
    if not math.isfinite(number):
        raise DataError("Non-finite numeric measurement")
    return number


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,200}", value):
        raise DataError("Invalid event ID; copy the exact string from USGS")
    return value


def official_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "earthquake.usgs.gov"
            or parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.fragment):
        raise DataError("Only HTTPS earthquake.usgs.gov URLs are supported")
    return url


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DataError(f"Redirect refused (HTTP {code}); inspect the official link")


def bounded_read(response, cap, deadline):
    declared = response.headers.get("Content-Length")
    if declared is not None:
        try:
            declared = int(declared)
        except ValueError as exc:
            raise DataError("Invalid Content-Length") from exc
        if not 0 <= declared <= cap:
            raise DataError(f"Response exceeds {cap} bytes or has invalid length")
    chunks, count = [], 0
    while True:
        if time.monotonic() > deadline:
            raise DataError("Request deadline exceeded")
        chunk = response.read(min(65536, cap + 1 - count))
        if not chunk:
            break
        chunks.append(chunk)
        count += len(chunk)
        if count > cap:
            raise DataError(f"Response exceeds {cap} bytes")
    if declared is not None and count != declared:
        raise DataError("Truncated response: Content-Length does not match")
    return b"".join(chunks)


def request(url, cap=JSON_CAP, timeout=30):
    official_url(url)
    started = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": "usgs-earthquakes-agent-skill/1.0", "Accept-Encoding": "identity"})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout) as response:
            status = response.status
            if status not in (200, 204):
                raise DataError(f"Unexpected HTTP {status}")
            body = bounded_read(response, cap, started + timeout)
            provenance = {
                "request_url": url, "retrieved_utc": utc_now(), "http_status": status,
                "response_bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                "etag": response.headers.get("ETag"), "last_modified": response.headers.get("Last-Modified"),
                "content_type": response.headers.get("Content-Type"),
            }
            return body, provenance
    except urllib.error.HTTPError as exc:
        meanings = {400: "invalid/too broad query; refine or split it", 404: "event/content not found", 409: "deleted event conflict", 429: "rate limited; wait before retrying"}
        raise DataError(f"HTTP {exc.code}: {meanings.get(exc.code, 'service failure; retry later if transient')}") from exc
    except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
        raise DataError("Network/TLS/timeout failure; no scientific result available") from exc
    except http.client.HTTPException as exc:
        raise DataError("Incomplete or malformed HTTP response; no scientific result available") from exc


def json_document(body, expected):
    try:
        document = json.loads(body)
    except (ValueError, UnicodeError) as exc:
        raise DataError("Invalid JSON response") from exc
    if not isinstance(document, dict) or document.get("type") != expected:
        raise DataError(f"Expected GeoJSON {expected}")
    return document


def feature_record(feature):
    if not isinstance(feature, dict) or feature.get("type") != "Feature":
        raise DataError("Invalid GeoJSON event feature")
    event_id = identifier(feature.get("id"))
    props = feature.get("properties")
    geometry = feature.get("geometry")
    if not isinstance(props, dict):
        raise DataError("Missing event properties")
    if geometry is None:
        coords = [None, None, None]
    elif (not isinstance(geometry, dict) or geometry.get("type") != "Point"
          or not isinstance(geometry.get("coordinates"), list) or len(geometry["coordinates"]) != 3):
        raise DataError("Expected longitude/latitude/depth Point")
    else:
        coords = [numeric(v) for v in geometry["coordinates"]]
    lon, lat, depth = coords
    if lon is not None and not -180 <= lon <= 180 or lat is not None and not -90 <= lat <= 90:
        raise DataError("Event coordinate outside geographic range")
    return {
        "id": event_id, "longitude_deg": lon, "latitude_deg": lat, "depth_km": depth,
        "origin_time_utc": epoch_utc(props.get("time")), "updated_utc": epoch_utc(props.get("updated")),
        "magnitude": numeric(props.get("mag")), "magnitude_type": props.get("magType"),
        "event_type": props.get("type"), "status": props.get("status"), "place": props.get("place"),
        "network": props.get("net"), "code": props.get("code"), "aliases": props.get("ids"),
        "sources": props.get("sources"), "event_url": props.get("url"), "detail_url": props.get("detail"),
    }


def csv_records(body):
    try:
        text = body.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if not {"id", "time", "updated", "latitude", "longitude", "depth", "mag", "magType"} <= set(reader.fieldnames or []):
            raise DataError("Missing CSV event columns")
        rows = list(reader)
    except (UnicodeError, csv.Error) as exc:
        raise DataError("Invalid CSV response") from exc
    records = []
    for row in rows:
        identifier(row["id"])
        if None in row or any(v is None for v in row.values()):
            raise DataError("Malformed CSV row")
        lon, lat = numeric(row["longitude"]), numeric(row["latitude"])
        if lon is not None and not -180 <= lon <= 180 or lat is not None and not -90 <= lat <= 90:
            raise DataError("CSV event coordinate outside geographic range")
        records.append({
            "id": row["id"], "origin_time_utc": parse_time(row["time"]).isoformat().replace("+00:00", "Z"),
            "updated_utc": parse_time(row["updated"]).isoformat().replace("+00:00", "Z"),
            "longitude_deg": lon, "latitude_deg": lat,
            "depth_km": numeric(row["depth"]), "magnitude": numeric(row["mag"]), "magnitude_type": row["magType"],
            "event_type": row.get("type"), "status": row.get("status"), "place": row.get("place"),
            "location_source": row.get("locationSource"), "magnitude_source": row.get("magSource"),
            "horizontal_error_km": numeric(row.get("horizontalError")), "depth_error_km": numeric(row.get("depthError")),
            "magnitude_error": numeric(row.get("magError")), "magnitude_station_count": numeric(row.get("magNst")),
        })
    return text, records


def query_parameters(args):
    start, end = parse_time(args.start), parse_time(args.end)
    if not 0 < (end - start).total_seconds() <= 366 * 86400:
        raise DataError("Require end after start and at most 366 days; split larger intervals")
    if not 1 <= args.limit <= 1000 or args.offset < 1:
        raise DataError("Helper page limit is 1..1000 and offset starts at 1")
    params = {"starttime": start.isoformat(), "endtime": end.isoformat()}
    if args.event_type != "all":
        params["eventtype"] = args.event_type
    if args.updated_after:
        params["updatedafter"] = parse_time(args.updated_after).isoformat()
    for arg, key in (("min_magnitude", "minmagnitude"), ("max_magnitude", "maxmagnitude")):
        if getattr(args, arg) is not None:
            params[key] = numeric(getattr(args, arg))
    if args.min_magnitude is not None and args.max_magnitude is not None and args.min_magnitude > args.max_magnitude:
        raise DataError("Minimum magnitude exceeds maximum")
    circle = [args.latitude, args.longitude, args.radius_km]
    if any(v is not None for v in circle):
        if not all(v is not None for v in circle) or args.bbox:
            raise DataError("Use a complete circle OR a bounding box")
        lat, lon, radius = [numeric(v) for v in circle]
        if not -90 <= lat <= 90 or not -180 <= lon <= 180 or not 0 < radius <= 20001.6:
            raise DataError("Invalid circle degrees or radius km")
        params.update(latitude=lat, longitude=lon, maxradiuskm=radius)
    if args.bbox:
        west, south, east, north = [numeric(v) for v in args.bbox]
        if not -360 <= west < east <= 360 or not -90 <= south < north <= 90 or east - west > 360:
            raise DataError("Invalid west/south/east/north box; unwrap date-line east above 180")
        params.update(minlongitude=west, minlatitude=south, maxlongitude=east, maxlatitude=north)
    if args.review_status:
        params["reviewstatus"] = args.review_status
    return params


def service_url(method, params):
    return SERVICE + method + "?" + urllib.parse.urlencode(params)


def catalog_query(args):
    params = query_parameters(args)
    count_body, count_source = request(service_url("count", dict(params, format="text")), 1024, args.timeout)
    try:
        count = int(count_body)
    except ValueError as exc:
        raise DataError("Invalid count response") from exc
    if count < 0:
        raise DataError("Negative catalog count")
    if count > 20000:
        raise DataError("Count exceeds 20,000; split the time/region before paging")
    body, source = request(service_url("query", dict(params, format=args.format, limit=args.limit, offset=args.offset, orderby="time-asc")), JSON_CAP, args.timeout)
    if source["http_status"] == 204:
        raw, records = None, []
    elif args.format == "csv":
        raw, records = csv_records(body)
    else:
        raw = json_document(body, "FeatureCollection")
        if not isinstance(raw.get("features"), list):
            raise DataError("Missing GeoJSON features")
        records = [feature_record(f) for f in raw["features"]]
    if len(records) > args.limit or len({r["id"] for r in records}) != len(records):
        raise DataError("Unexpected oversized/duplicate catalog page")
    next_offset = args.offset + len(records)
    has_more = bool(records) and next_offset <= count
    return {"source": source, "count_source": count_source, "count_at_preflight": count,
            "offset": args.offset, "returned": len(records), "has_more_at_preflight": has_more,
            "next_offset": next_offset if has_more else None, "snapshot_atomic": False,
            "raw_format": args.format, "raw": raw, "events": records}


def feed(args):
    url = ROOT + f"/earthquakes/feed/v1.0/summary/{args.level}_{args.window}.geojson"
    body, source = request(url, JSON_CAP, args.timeout)
    raw = json_document(body, "FeatureCollection")
    if not isinstance(raw.get("features"), list):
        raise DataError("Missing feed features")
    return {"source": source, "raw_format": "geojson", "raw": raw,
            "events": [feature_record(f) for f in raw["features"]]}


def detail(args):
    event_id = identifier(args.event_id)
    url = service_url("query", {"eventid": event_id, "format": args.format})
    body, source = request(url, JSON_CAP, args.timeout)
    if source["http_status"] == 204:
        raise DataError("Event not found (HTTP 204)")
    if args.format == "csv":
        raw, records = csv_records(body)
        if len(records) != 1:
            raise DataError("Expected one CSV event")
        return {"source": source, "requested_id": event_id, "raw_format": "csv", "raw": raw, "events": records}
    raw = json_document(body, "Feature")
    record = feature_record(raw)
    alias_text = raw["properties"].get("ids")
    if alias_text is not None and not isinstance(alias_text, str):
        raise DataError("Invalid event alias list; expected a comma-separated string")
    aliases = (alias_text or "").split(",")
    if record["id"] != event_id and event_id not in aliases:
        raise DataError("Returned event does not match requested ID or aliases")
    return {"source": source, "requested_id": event_id, "raw_format": "geojson", "raw": raw,
            "events": [record], "products": product_inventory(raw)}


def product_inventory(raw):
    products = raw["properties"].get("products", {})
    if not isinstance(products, dict):
        raise DataError("Invalid products object")
    inventory = []
    for kind, versions in sorted(products.items()):
        if not isinstance(versions, list) or any(not isinstance(p, dict) for p in versions):
            raise DataError("Invalid product array")
        active = [p for p in versions if p.get("status") == "UPDATE"]
        ranked = sorted(active, key=lambda p: (numeric(p.get("preferredWeight")) or 0, numeric(p.get("updateTime")) or 0), reverse=True)
        preferred = ranked[0] if ranked else None
        for p in versions:
            contents = p.get("contents", {})
            # ComCat also emits [] for products with no downloadable content.
            if contents == []:
                contents = {}
            if not isinstance(contents, dict) or any(not isinstance(v, dict) for v in contents.values()):
                raise DataError("Invalid product contents")
            inventory.append({
                "type": kind, "id": p.get("id"), "source": p.get("source"), "code": p.get("code"),
                "update_time_ms": p.get("updateTime"), "update_utc": epoch_utc(p.get("updateTime")),
                "status": p.get("status"), "preferred_weight": p.get("preferredWeight"),
                "preferred_in_response": p is preferred, "properties": p.get("properties", {}),
                "contents": contents,
            })
    return inventory


def write_new(path, body):
    destination = Path(path)
    if destination.exists():
        raise DataError("Output already exists; choose a new filename")
    # Publish a verified complete temporary file without replacing an existing path.
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
        temp = Path(stream.name)
        try:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        if os.name == "nt":
            # On Windows, same-directory rename fails if the target exists.
            # It avoids requiring permission to create hard links.
            os.rename(temp, destination)
        else:
            # POSIX rename can overwrite, so use the no-clobber hard link.
            os.link(temp, destination)
    except FileExistsError as exc:
        raise DataError("Output already exists; choose a new filename") from exc
    finally:
        temp.unlink(missing_ok=True)


def download_product(args):
    # Re-discover the exact version; refuse silent replacement after updates.
    result = detail(argparse.Namespace(event_id=args.event_id, format="geojson", timeout=args.timeout))
    matches = [p for p in result["products"] if p["type"] == args.product_type and p["id"] == args.product_id]
    if len(matches) != 1 or matches[0]["status"] != "UPDATE":
        raise DataError("Exact active product version unavailable; inspect detail again")
    product = matches[0]
    content = product["contents"].get(args.content)
    if not isinstance(content, dict) or not content.get("url"):
        raise DataError("Exact content key unavailable; inspect product inventory")
    if not 1 <= args.max_bytes <= 50_000_000:
        raise DataError("Download cap must be 1..50,000,000 bytes")
    expected = content.get("length")
    if expected is not None and (isinstance(expected, bool) or not isinstance(expected, int) or not 0 <= expected <= args.max_bytes):
        raise DataError("Advertised product size exceeds cap or is invalid")
    body, source = request(content["url"], args.max_bytes, args.timeout)
    if source["http_status"] != 200 or not body:
        raise DataError("Empty product response")
    if expected is not None and len(body) != expected:
        raise DataError("Product byte count differs from content metadata; inspect updated detail")
    write_new(args.output, body)
    return {"source": source, "detail_source": result["source"], "event_id": result["events"][0]["id"],
            "requested_id": args.event_id, "product": product, "content_key": args.content,
            "output": str(Path(args.output)), "byte_count": len(body)}


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    f = commands.add_parser("feed", help="one bounded recent GeoJSON feed")
    f.add_argument("--window", choices=("hour", "day", "week", "month"), default="day")
    f.add_argument("--level", choices=("all", "1.0", "2.5", "4.5", "significant"), default="4.5")
    q = commands.add_parser("query", help="one explicit historical/custom catalog page")
    q.add_argument("--start", required=True)
    q.add_argument("--end", required=True)
    q.add_argument("--min-magnitude", type=float)
    q.add_argument("--max-magnitude", type=float)
    q.add_argument("--latitude", type=float)
    q.add_argument("--longitude", type=float)
    q.add_argument("--radius-km", type=float)
    q.add_argument("--bbox", type=float, nargs=4, metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    q.add_argument("--limit", type=int, default=100)
    q.add_argument("--offset", type=int, default=1)
    q.add_argument("--event-type", choices=("earthquake", "all"), default="earthquake")
    q.add_argument("--review-status", choices=("automatic", "reviewed"))
    q.add_argument("--updated-after")
    q.add_argument("--format", choices=("geojson", "csv"), default="geojson")
    d = commands.add_parser("detail", help="event detail/products or preferred CSV uncertainty fields")
    d.add_argument("--event-id", required=True)
    d.add_argument("--format", choices=("geojson", "csv"), default="geojson")
    p = commands.add_parser("product", help="download one exact product content; no decoding")
    p.add_argument("--event-id", required=True)
    p.add_argument("--product-type", required=True)
    p.add_argument("--product-id", required=True)
    p.add_argument("--content", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--max-bytes", type=int, default=5_000_000)
    for command in (f, q, d, p):
        command.add_argument("--timeout", type=float, default=30, help="per-request seconds, maximum 60")
    return cli


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if not math.isfinite(args.timeout) or not 0 < args.timeout <= 60:
            raise DataError("Timeout must be finite and in (0,60] seconds")
        result = {"feed": feed, "query": catalog_query, "detail": detail, "product": download_product}[args.command](args)
        # ASCII JSON escapes survive Windows default encodings and remain valid UTF-8.
        print(json.dumps(result, ensure_ascii=True, allow_nan=False, indent=2))
        return 0
    except (DataError, OSError, ValueError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
