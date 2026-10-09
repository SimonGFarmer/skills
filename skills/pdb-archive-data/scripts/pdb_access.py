"""Bounded, read-only official RCSB retrieval; no CIF parser or scientific inference."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import http.client
import json
import math
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
ENTRY_BASE = "https://data.rcsb.org/rest/v1/core/entry/"
CIF_BASE = "https://files.rcsb.org/download/"
MIB = 1024 * 1024
MAX_PAGES = 5
MAX_ROWS = 100


class AccessError(Exception):
    pass


def accession(value: str) -> str:
    if re.fullmatch(r"[1-9][A-Za-z0-9]{3}", value):
        return value.upper()
    if re.fullmatch(r"pdb_[A-Za-z0-9]{8}", value, flags=re.IGNORECASE):
        return value.lower()
    raise AccessError("Expected classic PDB accession or pdb_ plus eight alphanumerics")


@dataclass(frozen=True)
class Limits:
    timeout: float = 20.0
    deadline: float = 30.0
    json_bytes: int = 2 * MIB
    cif_bytes: int = 32 * MIB

    def __post_init__(self):
        for name, value, upper in (("timeout", self.timeout, 60),
                                   ("deadline", self.deadline, 120)):
            if not math.isfinite(value) or not 0 < value <= upper:
                raise AccessError(f"{name} must be positive and <= {upper}")
        for name, value, upper in (("json_bytes", self.json_bytes, 8 * MIB),
                                   ("cif_bytes", self.cif_bytes, 64 * MIB)):
            if type(value) is not int or not 1 <= value <= upper:
                raise AccessError(f"{name} must be an integer in 1..{upper}")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AccessError(f"Redirect refused (HTTP {code}); review official endpoint")


def official_url(url: str) -> bool:
    if url == SEARCH_URL:
        return True
    if url.startswith(ENTRY_BASE):
        suffix = url[len(ENTRY_BASE):]
    elif url.startswith(CIF_BASE) and url.endswith(".cif"):
        suffix = url[len(CIF_BASE):-4]
    else:
        return False
    try:
        accession(suffix)
        return True
    except AccessError:
        return False


def fetch(url: str, limits: Limits, cap: int, payload: dict | None = None,
          *, opener=None, monotonic=time.monotonic) -> tuple[bytes, dict]:
    if not official_url(url):
        raise AccessError("URL is outside the fixed official endpoint set")
    endpoint_cap = limits.cif_bytes if url.startswith(CIF_BASE) else limits.json_bytes
    if type(cap) is not int or not 1 <= cap <= endpoint_cap:
        raise AccessError("Invalid response cap")
    headers = {"User-Agent": "pdb-archive-data/1.0", "Accept-Encoding": "identity"}
    data = None
    if payload is not None:
        if url != SEARCH_URL:
            raise AccessError("POST only supported for the fixed search endpoint")
        data = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode("utf-8")
        if len(data) > 8192:
            raise AccessError("Query payload too large")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    opener = opener or urllib.request.build_opener(NoRedirect())
    started = monotonic()
    try:
        with opener.open(request, timeout=min(limits.timeout, limits.deadline)) as response:
            status = response.status
            if status not in (200, 204) or (status == 204 and url != SEARCH_URL):
                raise AccessError(f"Unexpected HTTP {status}")
            if response.geturl() != url:
                raise AccessError("Response URL differs from requested endpoint")
            encoding = response.headers.get("Content-Encoding", "identity").lower()
            if encoding not in ("", "identity"):
                raise AccessError("Unexpected Content-Encoding; no decompression fallback")
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    declared = int(declared)
                except ValueError as exc:
                    raise AccessError("Malformed Content-Length") from exc
                if declared < 0 or declared > cap:
                    raise AccessError("Response exceeds byte cap")
            chunks, size = [], 0
            while True:
                if monotonic() - started > limits.deadline:
                    raise AccessError("Request deadline exceeded")
                chunk = response.read(min(65536, cap - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                if size > cap:
                    raise AccessError("Response exceeds byte cap")
                chunks.append(chunk)
            if monotonic() - started > limits.deadline:
                raise AccessError("Request deadline exceeded")
            raw = b"".join(chunks)
            if declared is not None and declared != len(raw):
                raise AccessError("Truncated or inconsistent Content-Length")
            if status == 204 and raw:
                raise AccessError("Unexpected body for HTTP 204")
            provenance = {"url": url, "http_status": status,
                          "retrieved_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                          "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                          "etag": response.headers.get("ETag"),
                          "last_modified": response.headers.get("Last-Modified")}
            return raw, provenance
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as exc:
        raise AccessError(f"Official retrieval failed: {exc}; no retry or fallback") from exc


def decode_json(raw: bytes) -> dict:
    def reject_constant(value):
        raise ValueError(f"Non-JSON numeric constant {value}")
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Numeric overflow in JSON response")
        return number
    try:
        result = json.loads(raw.decode("utf-8"), parse_constant=reject_constant,
                            parse_float=finite_float)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise AccessError("Invalid JSON response") from exc
    if not isinstance(result, dict):
        raise AccessError("Expected a JSON object")
    return result


def date_value(value: str) -> str:
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise AccessError("Release date must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise AccessError("Release date must be YYYY-MM-DD")
    return value


def search_query(text: str, rows: int = 10, page: int = 1,
                 method: str | None = None, after: str | None = None,
                 before: str | None = None) -> dict:
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 256:
        raise AccessError("Search text must contain 1..256 characters")
    if type(rows) is not int or not 1 <= rows <= MAX_ROWS:
        raise AccessError("Rows must be in 1..100")
    if type(page) is not int or not 1 <= page <= MAX_PAGES:
        raise AccessError("Page must be in 1..5")

    def terminal(field, operator, value):
        return {"type": "terminal", "service": "text", "parameters": {
            "attribute": field, "operator": operator, "value": value}}

    nodes = [{"type": "terminal", "service": "full_text", "parameters": {"value": text}},
             terminal("rcsb_entry_info.structure_determination_methodology", "exact_match",
                      "experimental")]
    if method is not None:
        if not isinstance(method, str) or not 1 <= len(method.strip()) <= 80:
            raise AccessError("Method must contain 1..80 characters")
        nodes.append(terminal("exptl.method", "exact_match", method))
    if after:
        nodes.append(terminal("rcsb_accession_info.initial_release_date", "greater_or_equal",
                              date_value(after)))
    if before:
        nodes.append(terminal("rcsb_accession_info.initial_release_date", "less_or_equal",
                              date_value(before)))
    if after and before and after > before:
        raise AccessError("Release-date range is reversed")
    return {"query": {"type": "group", "logical_operator": "and", "nodes": nodes},
            "return_type": "entry", "request_options": {
                "results_content_type": ["experimental"],
                "paginate": {"start": (page - 1) * rows, "rows": rows}}}


def search(text: str, limits: Limits, rows=10, page=1, method=None, after=None,
           before=None, *, fetcher=fetch) -> tuple[bytes, dict]:
    query = search_query(text, rows, page, method, after, before)
    raw, provenance = fetcher(SEARCH_URL, limits, limits.json_bytes, query)
    if provenance["http_status"] == 204:
        result, total, hits = None, 0, []
    else:
        result = decode_json(raw)
        total, hits = result.get("total_count"), result.get("result_set")
        if type(total) is not int or total < 0 or not isinstance(hits, list):
            raise AccessError("Malformed search result count/set")
        if len(hits) > rows or len(hits) > total:
            raise AccessError("Search result exceeds requested page/count")
        for hit in hits:
            if not isinstance(hit, dict) or not isinstance(hit.get("identifier"), str):
                raise AccessError("Malformed search hit")
            accession(hit["identifier"])
    has_more = total > page * rows
    manifest = {"scope": "current experimental PDB entry annotation search",
                "query": query, "response": provenance, "page": page, "rows": rows,
                "total_count": total, "returned_count": len(hits),
                "identifiers": [hit["identifier"] for hit in hits],
                "has_more": has_more, "next_page": page + 1 if has_more and page < MAX_PAGES else None,
                "truncated_by_page_limit": has_more and page == MAX_PAGES,
                "snapshot_consistency": "not guaranteed between requests"}
    return raw, manifest


SUMMARY_PATHS = ("struct.title", "exptl", "rcsb_entry_info.resolution_combined",
                 "rcsb_entry_info.structure_determination_methodology", "rcsb_accession_info",
                 "pdbx_audit_revision_history")


def metadata_summary(document: dict) -> dict:
    values, missing = {}, []
    for path in SUMMARY_PATHS:
        current = document
        for key in path.split("."):
            if not isinstance(current, dict) or key not in current:
                missing.append(path)
                current = None
                break
            current = current[key]
        values[path] = current
    return {"values": values, "missing_fields": missing,
            "units": {"rcsb_entry_info.resolution_combined": "angstrom"}}


def get_entry(value: str, limits: Limits, *, fetcher=fetch) -> tuple[bytes, bytes, dict]:
    entry_id = accession(value)
    # Existing four-character IDs have a defined pdb_0000 alias. Current RCSB
    # endpoints still require the classic form for these entries.
    service_id = entry_id
    if entry_id.startswith("pdb_0000") and re.fullmatch(r"[1-9][a-z0-9]{3}", entry_id[8:]):
        service_id = entry_id[8:].upper()
    raw_metadata, meta_provenance = fetcher(ENTRY_BASE + service_id, limits, limits.json_bytes)
    metadata = decode_json(raw_metadata)
    info = metadata.get("rcsb_entry_info")
    if not isinstance(info, dict) or info.get("structure_determination_methodology") != "experimental":
        raise AccessError("Metadata does not explicitly identify an experimental structure")
    returned_id = metadata.get("rcsb_id")
    if not isinstance(returned_id, str):
        raise AccessError("Metadata missing entry identity")

    def expanded(identifier):
        normalized = accession(identifier)
        return "pdb_0000" + normalized.lower() if len(normalized) == 4 else normalized

    if expanded(returned_id) != expanded(entry_id):
        raise AccessError("Metadata accession differs from request")
    raw_cif, cif_provenance = fetcher(CIF_BASE + service_id + ".cif", limits, limits.cif_bytes)
    try:
        cif_text = raw_cif.decode("utf-8")
    except UnicodeError as exc:
        raise AccessError("Coordinate response is not UTF-8 mmCIF text") from exc
    # A format sanity check only; deliberately not a partial CIF parser.
    if not re.match(r"(?:\s|#[^\n]*(?:\n|$))*data_\S+", cif_text):
        raise AccessError("Coordinate response lacks a CIF data-block header")
    manifest = {"scope": "current deposited coordinate file; assembly/model selection not performed",
                "requested_accession": value, "normalized_accession": entry_id,
                "service_accession": service_id,
                "metadata": meta_provenance, "coordinates": cif_provenance,
                "summary": metadata_summary(metadata),
                "coordinate_revision": "not parsed; inspect raw CIF audit categories with a mature parser",
                "snapshot_consistency": "two independent requests; verify revision agreement",
                "cif_validation": "UTF-8/data-block sanity only; not scientific or syntax validation"}
    return raw_metadata, raw_cif, manifest


def save_artifacts(directory: Path, artifacts: dict[str, bytes]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if any((directory / name).exists() for name in artifacts):
        raise AccessError("Output artifact already exists; choose a new output directory")
    # Exclusive creation also protects against a concurrent writer. An I/O failure
    # may leave a partial set; absent manifest means retrieval is not complete.
    for name, raw in artifacts.items():
        with (directory / name).open("xb") as handle:
            handle.write(raw)


def json_artifact(value: dict) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    search_parser = sub.add_parser("search")
    search_parser.add_argument("--text", required=True)
    search_parser.add_argument("--rows", type=int, default=10)
    search_parser.add_argument("--page", type=int, default=1)
    search_parser.add_argument("--method")
    search_parser.add_argument("--released-after")
    search_parser.add_argument("--released-before")
    entry_parser = sub.add_parser("entry")
    entry_parser.add_argument("accession")
    for command_parser in (search_parser, entry_parser):
        command_parser.add_argument("--out", type=Path, required=True)
        command_parser.add_argument("--timeout", type=float, default=20)
        command_parser.add_argument("--deadline", type=float, default=30)
        command_parser.add_argument("--json-bytes", type=int, default=2 * MIB)
        command_parser.add_argument("--cif-bytes", type=int, default=32 * MIB)
    args = parser.parse_args(argv)
    try:
        limits = Limits(args.timeout, args.deadline, args.json_bytes, args.cif_bytes)
        if args.command == "search":
            raw, manifest = search(args.text, limits, args.rows, args.page, args.method,
                                   args.released_after, args.released_before)
            artifacts = {"search.response.json": raw,
                         "search.manifest.json": json_artifact(manifest)}
        else:
            metadata, cif, manifest = get_entry(args.accession, limits)
            base = manifest["normalized_accession"]
            artifacts = {base + ".entry.json": metadata, base + ".cif": cif,
                         base + ".manifest.json": json_artifact(manifest)}
        save_artifacts(args.out, artifacts)
        print(json.dumps({"output_directory": str(args.out), "files": list(artifacts)}))
        return 0
    except (AccessError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
