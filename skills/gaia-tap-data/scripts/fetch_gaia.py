#!/usr/bin/env python3
"""Bounded anonymous ESA Gaia DR3 cone retrieval; Python 3.10+, stdlib only."""

import argparse
from datetime import datetime, timezone
import http.client
import json
import math
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlencode, urljoin, urlsplit
import xml.etree.ElementTree as ET

ENDPOINT = "https://gea.esac.esa.int/tap-server/tap/sync"
TABLE = "gaiadr3.gaia_source"
MAX_BYTES = 8 * 1024 * 1024
MAX_TIMEOUT = 30.0
COLUMNS = (
    "source_id", "ref_epoch", "ra", "dec", "ra_error", "dec_error",
    "parallax", "parallax_error", "pmra", "pmdec", "pmra_error", "pmdec_error",
    "ra_dec_corr", "ra_parallax_corr", "ra_pmra_corr", "ra_pmdec_corr",
    "dec_parallax_corr", "dec_pmra_corr", "dec_pmdec_corr",
    "parallax_pmra_corr", "parallax_pmdec_corr", "pmra_pmdec_corr",
    "phot_g_mean_mag", "bp_rp", "ruwe", "astrometric_params_solved",
)
EXPECTED_UNITS = {name: "dimensionless" for name in COLUMNS}
EXPECTED_UNITS.update({name: "mas" for name in (
    "ra_error", "dec_error", "parallax", "parallax_error")})
EXPECTED_UNITS.update({name: "mas/year" for name in (
    "pmra", "pmdec", "pmra_error", "pmdec_error")})
EXPECTED_UNITS.update(source_id="identifier", ref_epoch="Julian year (TCB)",
                      ra="degree (ICRS)", dec="degree (ICRS)",
                      phot_g_mean_mag="mag", bp_rp="mag",
                      astrometric_params_solved="bit mask")
REQUIRED = {"source_id", "ref_epoch", "ra", "dec", "pmra", "pmdec"}


class GaiaError(ValueError):
    """A bounded retrieval or response-contract failure."""


def finite(value, label):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise GaiaError(f"{label} must be numeric") from exc
    if not math.isfinite(number):
        raise GaiaError(f"{label} must be finite")
    return number


def validate_inputs(ra, dec, radius, limit, timeout, max_bytes):
    ra, dec, radius = (finite(value, label) for value, label in (
        (ra, "ra"), (dec, "dec"), (radius, "radius")))
    timeout = finite(timeout, "timeout")
    if not 0 <= ra < 360 or not -90 <= dec <= 90:
        raise GaiaError("ra must be [0,360); dec must be [-90,90] degrees")
    if not 0 < radius <= 1:
        raise GaiaError("radius must be >0 and <=1 degree")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise GaiaError("limit must be an integer from 1 through 1000")
    if not 0 < timeout <= MAX_TIMEOUT:
        raise GaiaError("timeout must be >0 and <=30 seconds")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= MAX_BYTES:
        raise GaiaError("max_bytes must be a positive integer <=8388608")
    return ra, dec, radius


def build_query(ra, dec, radius, limit):
    validate_inputs(ra, dec, radius, limit, MAX_TIMEOUT, MAX_BYTES)
    return (
        f"SELECT TOP {limit + 1} {', '.join(COLUMNS)} FROM {TABLE} "
        f"WHERE CONTAINS(POINT('ICRS',ra,dec),"
        f"CIRCLE('ICRS',{float(ra):.12g},{float(dec):.12g},{float(radius):.12g}))=1 "
        "AND pmra IS NOT NULL AND pmdec IS NOT NULL "
        "ORDER BY phot_g_mean_mag ASC, source_id ASC"
    )


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise GaiaError("request deadline exceeded")
    return seconds


def allowed_url(url):
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname != "gea.esac.esa.int"
            or parts.port not in (None, 443) or parts.username or parts.password
            or not parts.path.startswith("/tap-server/") or parts.fragment):
        raise GaiaError("redirect is outside the fixed ESA service")
    return parts


def read_bounded(response, transport_socket, deadline, max_bytes):
    encoding = response.getheader("Content-Encoding", "identity").lower().strip()
    if encoding not in ("", "identity"):
        raise GaiaError("compressed response unsupported; expected plain VOTable XML")
    declared = response.getheader("Content-Length")
    if declared is not None:
        try:
            declared = int(declared)
        except ValueError as exc:
            raise GaiaError("invalid Content-Length") from exc
        if declared < 0 or declared > max_bytes:
            raise GaiaError("response exceeds byte cap")
    chunks, size = [], 0
    while True:
        transport_socket.settimeout(remaining(deadline))
        chunk = response.read1(min(65536, max_bytes - size + 1))
        remaining(deadline)
        if not chunk:
            break
        size += len(chunk)
        if size > max_bytes:
            raise GaiaError("response exceeds byte cap")
        chunks.append(chunk)
    if declared is not None and size != declared:
        raise GaiaError("response length does not match Content-Length")
    return b"".join(chunks)


def fetch_xml(query, limit, timeout=MAX_TIMEOUT, max_bytes=MAX_BYTES):
    """One request, bounded same-service redirects, no retry or fallback."""
    deadline = time.monotonic() + timeout
    body = urlencode({"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "votable_plain",
                      "MAXREC": str(limit + 1), "QUERY": query}).encode("ascii")
    url, method = ENDPOINT, "POST"
    for redirects in range(3):
        parts = allowed_url(url)
        connection = http.client.HTTPSConnection(parts.hostname, timeout=remaining(deadline))
        try:
            connection.connect()
            transport_socket = connection.sock
            transport_socket.settimeout(remaining(deadline))
            path = parts.path + ("?" + parts.query if parts.query else "")
            headers = {"Accept": "application/x-votable+xml, application/xml",
                       "Accept-Encoding": "identity", "User-Agent": "gaia-tap-data/1.0"}
            if method == "POST":
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            connection.request(method, path, body=body if method == "POST" else None, headers=headers)
            transport_socket.settimeout(remaining(deadline))
            response = connection.getresponse()
            remaining(deadline)
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location or redirects == 2:
                    raise GaiaError("missing redirect target or redirect cap exceeded")
                url = urljoin(url, location)
                allowed_url(url)
                if response.status == 303:
                    method = "GET"
                continue
            if response.status != 200:
                raise GaiaError(f"ESA service returned HTTP {response.status}")
            return read_bounded(response, transport_socket, deadline, max_bytes), url
        except (OSError, http.client.HTTPException) as exc:
            raise GaiaError(f"ESA request failed ({type(exc).__name__}); no result written") from exc
        finally:
            connection.close()
    raise GaiaError("redirect cap exceeded")


def local_name(element):
    return element.tag.rsplit("}", 1)[-1]


def parse_cell(text, name):
    value = (text or "").strip()
    if not value:
        if name in REQUIRED:
            raise GaiaError(f"missing required {name}")
        return None
    if name == "source_id":
        if not re.fullmatch(r"[0-9]+", value) or not 0 < int(value) <= 2**63 - 1:
            raise GaiaError("invalid source_id")
        return value
    if name == "astrometric_params_solved":
        if value not in ("3", "31", "95"):
            raise GaiaError("invalid astrometric_params_solved")
        return int(value)
    number = finite(value, name)
    if name.endswith("_corr") and not -1 <= number <= 1:
        raise GaiaError(f"correlation outside [-1,1]: {name}")
    if name.endswith("_error") and number < 0:
        raise GaiaError(f"negative standard error: {name}")
    if name == "ruwe" and number < 0:
        raise GaiaError("negative ruwe")
    if name == "ra" and not 0 <= number < 360:
        raise GaiaError("invalid returned ra")
    if name == "dec" and not -90 <= number <= 90:
        raise GaiaError("invalid returned dec")
    return number


def check_field(field, name):
    datatype = field.attrib.get("datatype")
    allowed = {"long"} if name == "source_id" else (
        {"int", "short", "byte", "long"} if name == "astrometric_params_solved"
        else {"float", "double"})
    if datatype not in allowed:
        raise GaiaError(f"unsupported datatype for {name}: {datatype}")
    # Missing units remain explicitly missing in reported metadata; present units
    # must agree with the DR3 contract rather than silently changing a quantity.
    unit = field.attrib.get("unit")
    if unit:
        normalized = unit.lower().replace(" ", "").replace("**", "^")
        if name in ("ra", "dec"):
            accepted = {"deg", "degree", "degrees"}
        elif name in ("ra_error", "dec_error", "parallax", "parallax_error"):
            accepted = {"mas"}
        elif name in ("pmra", "pmdec", "pmra_error", "pmdec_error"):
            accepted = {"mas/yr", "mas/year", "mas.yr-1", "mas.yr^-1", "masyr-1", "masyr^-1"}
        elif name == "ref_epoch":
            accepted = {"yr", "year", "years"}
        elif name in ("phot_g_mean_mag", "bp_rp"):
            accepted = {"mag"}
        else:
            accepted = {"1", "dimensionless"}
        if normalized not in accepted:
            raise GaiaError(f"unit disagrees with DR3 contract for {name}: {unit}")
    values = [element for element in field if local_name(element) == "VALUES"]
    if len(values) > 1:
        raise GaiaError(f"multiple VALUES elements for {name}")
    return values[0].attrib.get("null") if values else None


def parse_votable(raw, limit, max_bytes=MAX_BYTES):
    if len(raw) > max_bytes:
        raise GaiaError("response exceeds byte cap")
    try:
        xml = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise GaiaError("only UTF-8 VOTable XML is supported") from exc
    if "\x00" in xml:
        raise GaiaError("only UTF-8 VOTable XML is supported")
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", xml, flags=re.I):
        raise GaiaError("DTD and entity declarations unsupported")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise GaiaError("malformed VOTable XML") from exc
    if local_name(root) != "VOTABLE":
        raise GaiaError("expected VOTABLE root")
    statuses = [element.attrib.get("value", "").upper() for element in root.iter()
                if local_name(element) == "INFO" and element.attrib.get("name") == "QUERY_STATUS"]
    if not statuses or any(status not in ("OK", "ERROR", "OVERFLOW") for status in statuses):
        raise GaiaError("missing or unknown QUERY_STATUS")
    if "ERROR" in statuses:
        raise GaiaError("ESA QUERY_STATUS ERROR, including trailing status")
    resources = [element for element in root.iter()
                 if local_name(element) == "RESOURCE" and element.attrib.get("type") == "results"]
    if len(resources) != 1:
        raise GaiaError("expected one results RESOURCE")
    tables = [element for element in resources[0] if local_name(element) == "TABLE"]
    if len(tables) != 1:
        raise GaiaError("expected one results TABLE")
    table = tables[0]
    fields = [element for element in table if local_name(element) == "FIELD"]
    names = [field.attrib.get("name") or field.attrib.get("ID") for field in fields]
    if names != list(COLUMNS):
        raise GaiaError("returned FIELD names/order do not match requested schema")
    null_sentinels = [check_field(field, name) for field, name in zip(fields, names)]
    data_elements = [element for element in table if local_name(element) == "DATA"]
    if len(data_elements) != 1 or len(data_elements[0]) != 1 or local_name(data_elements[0][0]) != "TABLEDATA":
        raise GaiaError("only TABLEDATA VOTable serialization is supported")
    rows = []
    for tr in data_elements[0][0]:
        if local_name(tr) != "TR":
            raise GaiaError("unexpected TABLEDATA child")
        if len(rows) >= limit + 1:
            raise GaiaError("service exceeded explicit query row cap")
        cells = list(tr)
        if len(cells) != len(fields) or any(local_name(cell) != "TD" or len(cell) for cell in cells):
            raise GaiaError("row width or cell type does not match FIELD schema")
        rows.append({name: parse_cell(None if sentinel is not None and (cell.text or "").strip() == sentinel else cell.text, name)
                     for name, cell, sentinel in zip(names, cells, null_sentinels)})
    overflow = "OVERFLOW" in statuses
    return {
        "rows": rows[:limit], "returned_rows": len(rows), "included_rows": min(len(rows), limit),
        "selection_limited": len(rows) > limit, "service_overflow": overflow,
        "incomplete": overflow or len(rows) > limit,
        "query_status": statuses,
        "reported_fields": [{"name": name, "unit": field.attrib.get("unit"),
                             "datatype": field.attrib.get("datatype")}
                            for name, field in zip(names, fields)],
    }


def retrieve(ra, dec, radius, limit=100, timeout=MAX_TIMEOUT, max_bytes=MAX_BYTES):
    ra, dec, radius = validate_inputs(ra, dec, radius, limit, timeout, max_bytes)
    query = build_query(ra, dec, radius, limit)
    raw, result_url = fetch_xml(query, limit, timeout, max_bytes)
    result = parse_votable(raw, limit, max_bytes)
    result.update({
        "provenance": {"service": ENDPOINT, "result_url": result_url, "table": TABLE,
                       "retrieved_at_utc": datetime.now(timezone.utc).isoformat(), "query": query,
                       "response_bytes": len(raw), "row_cap_requested": limit + 1,
                       "timeout_seconds": timeout, "byte_cap": max_bytes},
        "selection": {"ra_deg": ra, "dec_deg": dec, "radius_deg": radius,
                      "display_limit": limit, "ordering": "phot_g_mean_mag ASC, source_id ASC",
                      "membership_claim": False},
        "expected_units": EXPECTED_UNITS,
        "notes": ["Bright field selection; not a representative or complete population.",
                  "Null measurements retained; source IDs are decimal strings.",
                  "Expected units are the DR3 contract; reported FIELD metadata is retained separately."],
    })
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ra", type=float, required=True)
    parser.add_argument("--dec", type=float, required=True)
    parser.add_argument("--radius", type=float, required=True, help="degrees, >0 and <=1")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=MAX_TIMEOUT)
    parser.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    created = False
    try:
        if args.out.exists():
            raise GaiaError("output already exists; choose a new filename")
        result = retrieve(args.ra, args.dec, args.radius, args.limit, args.timeout, args.max_bytes)
        serialized = json.dumps(result, indent=2, allow_nan=False) + "\n"
        with args.out.open("x", encoding="utf-8") as handle:
            created = True
            handle.write(serialized)
        print(f"Wrote {result['included_rows']} rows to {args.out}; incomplete={result['incomplete']}")
        return 0
    except (GaiaError, OSError) as exc:
        if created:
            args.out.unlink(missing_ok=True)
        print(f"Gaia retrieval failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
