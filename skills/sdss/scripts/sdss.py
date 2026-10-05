#!/usr/bin/env python3
"""Bounded public SDSS catalog queries and exact-record spectrum downloads."""
import argparse
import hashlib
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

ROOT = "https://skyserver.sdss.org"
MAX_JSON = 2_000_000
ID_FIELDS = ("allspec_id", "specobjid", "sdss_id", "objid")


class DataError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DataError(f"Redirect refused (HTTP {code}); inspect the official archive link")


def identifier(value, numeric=False):
    pattern = r"[0-9]{1,40}" if numeric else r"[A-Za-z0-9_.-]{1,200}"
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise DataError("Invalid identifier; copy its exact string from the catalog")
    return value


def cone(ra, dec, radius):
    if not all(math.isfinite(v) for v in (ra, dec, radius)):
        raise DataError("Cone coordinates and radius must be finite")
    if not 0 <= ra < 360 or not -90 <= dec <= 90 or not 0 < radius <= 60:
        raise DataError("Require RA [0,360), Dec [-90,90] degrees and radius (0,60] arcminutes")
    return f"{ra:.15g},{dec:.15g},{radius:.15g}"


def bounded_read(response, cap, deadline=None):
    declared = response.headers.get("Content-Length")
    if declared is not None:
        declared = int(declared)
        if declared < 0:
            raise DataError("Invalid negative Content-Length")
        if declared > cap:
            raise DataError(f"Response exceeds {cap} bytes")
    chunks, count = [], 0
    while True:
        if deadline is not None and time.monotonic() > deadline:
            raise DataError("Total request deadline exceeded")
        chunk = response.read(min(65536, cap + 1 - count))
        if not chunk:
            break
        chunks.append(chunk)
        count += len(chunk)
        if count > cap:
            raise DataError(f"Response exceeds {cap} bytes")
    if declared is not None and count != declared:
        raise DataError("Response ended before its declared Content-Length")
    return b"".join(chunks)


def request(url, cap, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "sdss-agent-skill/1.0", "Accept-Encoding": "identity"})
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=timeout) as response:
        return bounded_read(response, cap, time.monotonic() + timeout)


def sql_rows(sql, release, timeout):
    url = f"{ROOT}/{release}/SkyServerWS/SearchTools/SqlSearch?" + urllib.parse.urlencode({"format": "json", "cmd": sql})
    body = request(url, MAX_JSON, timeout)
    try:
        tables = json.loads(body)
    except (ValueError, UnicodeError) as exc:
        raise DataError("Catalog returned invalid JSON") from exc
    if not isinstance(tables, list) or not tables or not isinstance(tables[0], dict) or not isinstance(tables[0].get("Rows"), list):
        raise DataError("Unexpected catalog response; no result table")
    rows = tables[0]["Rows"]
    if any(not isinstance(row, dict) or "error_message" in row for row in rows):
        raise DataError("Catalog SQL failed; no scientific result available")
    for row in rows:
        for key in ID_FIELDS:
            if key in row and row[key] is not None and not isinstance(row[key], str):
                raise DataError(f"Identifier {key} was not returned as a string")
    return rows, url


FIELDS = """a.allspec_id,cast(a.specobjid as varchar(40)) as specobjid,
cast(a.sdss_id as varchar(40)) as sdss_id,a.ra,a.dec,a.sdss_phase,
a.instrument,a.run2d,a.coadd,a.sas_url,a.plate_or_fps_field as plate,a.mjd,
a.fiberid,coalesce(s.class,l.class) as class,coalesce(s.subclass,l.subclass) as subclass,
coalesce(s.z,l.z) as z,coalesce(s.z_err,l.zErr) as z_err,
coalesce(s.zwarning,l.zWarning) as zwarning"""
JOINS = """left join spAll s on a.specobjid=s.specobjid
and a.run2d='v6_2_1' and a.coadd='daily' and a.instrument='boss'
left join SpecObjAll l on a.specobjid=l.specobjid and a.sdss_phase<5
and a.instrument in ('sdss','boss')"""
PHOTO_FIELDS = """cast(p.objID as varchar(40)) as objid,
cast(p.specObjID as varchar(40)) as specobjid,p.ra,p.dec,p.type,p.mode,p.clean,
p.psfMag_r,p.psfMagErr_r,p.cModelMag_r,p.cModelMagErr_r,p.extinction_r"""


def spectrum_release(url):
    if url is not None and not isinstance(url, str):
        raise DataError("Catalog archive URL is not a string")
    match = re.search(r"/sas/(dr\d+)/", url or "")
    return match.group(1).upper() if match else None


def enrich(row, photometry=False):
    row = dict(row)
    if photometry:
        row["photometry_release"] = "DR17"
        row["morphology"] = {3: "extended", 6: "point-like"}.get(row.get("type"), "unclassified")
        spectrum_id = row.get("specobjid")
        linked = isinstance(spectrum_id, str) and re.fullmatch(r"[0-9]{1,40}", spectrum_id) and int(spectrum_id) > 0
        row["spectrum_association"] = "exact DR17 specObjID" if linked else "none"
    else:
        row["catalog_release"] = "DR20"
        row["allspec_version"] = "1.0.2"
        row["archive_release"] = spectrum_release(row.get("sas_url"))
        phase = row.get("sdss_phase")
        row["parameter_source"] = ("DR20 spAll daily" if row.get("run2d") == "v6_2_1" and row.get("coadd") == "daily" and row.get("instrument") == "boss"
                                   else "DR17 SpecObjAll" if isinstance(phase, (int, float)) and phase < 5 and row.get("instrument") in ("sdss", "boss") else None)
        warning, z = row.get("zwarning"), row.get("z")
        row["pipeline_redshift_unflagged"] = (isinstance(warning, (int, float)) and warning == 0 and isinstance(z, (int, float)) and math.isfinite(z) and z > -1)
    return row


def query(args):
    photo = args.command in ("photo-cone", "photo-id")
    limit = args.limit
    if args.command in ("cone", "photo-cone"):
        position = cone(args.ra, args.dec, args.radius)
        after = identifier(args.after, numeric=photo) if args.after else None
        if photo:
            source = f"dbo.fGetNearbyObjEq({position}) n join PhotoObjAll p on p.objID=n.objID"
            where = "p.mode=1" + (f" and p.objID>{after}" if after else "")
            sql = f"select top {limit + 1} {PHOTO_FIELDS},n.distance from {source} where {where} order by p.objID"
        else:
            source = f"dbo.fGetNearbyAllspecEq({position}) n join allspec a on a.allspec_id=n.allspec_id {JOINS}"
            where = f"where a.allspec_id>'{after}'" if after else ""
            sql = f"select top {limit + 1} {FIELDS},n.distance from {source} {where} order by a.allspec_id"
    elif photo:
        value = identifier(args.id, numeric=True)
        sql = f"select top {limit + 1} {PHOTO_FIELDS} from PhotoObjAll p where p.objID={value} order by p.objID"
    else:
        value = identifier(args.id, numeric=args.id_type != "allspec_id")
        sql = f"select top {limit + 1} {FIELDS} from allspec a {JOINS} where a.{args.id_type}='{value}' order by a.allspec_id"
        if args.after:
            after = identifier(args.after)
            sql = sql.replace(" order by", f" and a.allspec_id>'{after}' order by")
    rows, url = sql_rows(" ".join(sql.split()), "dr17" if photo else "dr20", args.timeout)
    key = "objid" if photo else "allspec_id"
    if any(not isinstance(row.get(key), str) or not row[key] for row in rows):
        raise DataError("Catalog record identity is missing")
    if len({row[key] for row in rows}) != len(rows):
        raise DataError("Catalog returned ambiguous duplicate record identities")
    if len(rows) > limit + 1:
        raise DataError("Catalog violated row bound")
    more = len(rows) > limit
    rows = rows[:limit]
    return {"status": "ok" if rows else "empty", "query_url": url,
            "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "rows": [enrich(row, photo) for row in rows], "has_more": more,
            "next_after": rows[-1][key] if more else None,
            "ordering": "objid" if photo else "allspec_id"}


def archive_url(value):
    if not isinstance(value, str) or not value:
        raise DataError("No archive spectrum URL for this record")
    url = urllib.parse.urlsplit(value)
    if (url.scheme != "https" or url.netloc not in ("data.sdss.org", "dr20.sdss.org", "dr17.sdss.org")
            or url.query or url.fragment or not re.fullmatch(r"/sas/dr(?:17|20)/[A-Za-z0-9_./-]+\.fits(?:\.gz)?", url.path)
            or ".." in url.path):
        raise DataError("Unsupported archive URL; inspect its official data model before downloading")
    return value


def valis_delivery(row, sas_url, timeout):
    """Resolve the exact DR20 BOSS daily specLite product."""
    path = urllib.parse.urlsplit(sas_url).path
    pattern = (r"/sas/dr20/spectro/boss/redux/v6_2_1/spectra/daily/lite/[0-9]{3}XXX/"
               r"(?P<field>[0-9]{6})/(?P<mjd>[0-9]{5})/"
               r"spec-(?P=field)-(?P=mjd)-(?P<catalogid>[0-9]{1,40})\.fits")
    match = re.fullmatch(pattern, path)
    if (not match or row.get("instrument") != "boss" or row.get("coadd") != "daily"
            or row.get("run2d") != "v6_2_1" or row.get("sdss_phase") != 5
            or row.get("plate") != int(match["field"]) or row.get("mjd") != int(match["mjd"])):
        raise DataError("Valis delivery supports only matching DR20 BOSS v6_2_1 daily lite records; use SAS for other products")
    params = [("release", "DR20"), ("kwargs", f"fieldid={match['field']}"),
              ("kwargs", f"mjd={match['mjd']}"), ("kwargs", "run2d=v6_2_1"),
              ("kwargs", f"catalogid={match['catalogid']}")]
    qs = urllib.parse.urlencode(params)
    resolution_url = "https://api.sdss.org/valis/paths/specLite?" + qs + "&part=all"
    try:
        resolved = json.loads(request(resolution_url, MAX_JSON, timeout))
    except (ValueError, UnicodeError) as exc:
        raise DataError("Valis returned invalid path-resolution JSON") from exc
    if (not isinstance(resolved, dict) or resolved.get("exists") is not True
            or urllib.parse.urlsplit(archive_url(resolved.get("url"))).path != path):
        raise DataError("Valis path does not identify the exact existing ALLSPEC archive product")
    return "https://api.sdss.org/valis/file/specLite/download?" + qs, resolution_url


def download(args):
    identifier(args.id)
    args.id_type, args.limit, args.after = "allspec_id", 1, None
    args.command = "target"
    result = query(args)
    if len(result["rows"]) != 1 or result["has_more"]:
        raise DataError("Exact ALLSPEC record not found or ambiguous")
    row = result["rows"][0]
    if not row.get("sas_url"):
        return {"status": "no_spectrum", "record": row, "query_url": result["query_url"]}
    url = archive_url(row["sas_url"])
    output = Path(args.output)
    if output.exists():
        raise DataError("Output already exists; choose a new filename")
    delivery_url, resolution_url = url, None
    if args.delivery == "valis":
        delivery_url, resolution_url = valis_delivery(row, url, args.timeout)
    body = request(delivery_url, args.max_bytes, args.timeout)
    if url.endswith(".fits") and (not body.startswith(b"SIMPLE  =") or len(body) < 2880 or len(body) % 2880):
        raise DataError("Archive returned a non-FITS or truncated FITS payload")
    if url.endswith(".gz") and (not body.startswith(b"\x1f\x8b") or len(body) < 18):
        raise DataError("Archive returned a non-gzip payload")
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as handle:
            temp = Path(handle.name)
            handle.write(body)
        # Hard link is atomic and never overwrites a file created after the first check.
        os.link(temp, output)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return {"status": "downloaded", "record": row, "query_url": result["query_url"],
            "archive_url": url, "delivery": args.delivery, "delivery_url": delivery_url,
            "path_resolution_url": resolution_url, "output": str(output), "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(), "retrieved_at": result["retrieved_at"]}


def bounded_int(low, high):
    def parse(value):
        number = int(value)
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"must be {low}..{high}")
        return number
    return parse


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("cone", "target", "photo-cone", "photo-id", "spectrum"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--timeout", type=bounded_int(1, 120), default=30, help="socket timeout and checked total read deadline in seconds")
        if name.endswith("cone"):
            cmd.add_argument("--ra", type=float, required=True)
            cmd.add_argument("--dec", type=float, required=True)
            cmd.add_argument("--radius", type=float, required=True, help="arcminutes, helper cap 60")
        else:
            cmd.add_argument("--id", required=True)
        if name == "target":
            cmd.add_argument("--id-type", choices=("allspec_id", "sdss_id", "specobjid"), default="allspec_id")
        if name == "spectrum":
            cmd.add_argument("--output", required=True)
            cmd.add_argument("--delivery", choices=("sas", "valis"), default="sas",
                             help="Valis supports exact DR20 BOSS v6_2_1 daily lite products; SAS supports the accepted archive URLs")
            cmd.add_argument("--max-bytes", type=bounded_int(1, 50_000_000), default=16_000_000)
        else:
            cmd.add_argument("--limit", type=bounded_int(1, 1000), default=100)
            if name != "photo-id":
                cmd.add_argument("--after", help="next_after from the same query; ID ordering, not proximity")
    return p


def main():
    try:
        args = parser().parse_args()
        result = download(args) if args.command == "spectrum" else query(args)
        print(json.dumps(result, allow_nan=False, indent=2))
    except (DataError, urllib.error.URLError, TimeoutError, socket.timeout, OSError, ValueError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
