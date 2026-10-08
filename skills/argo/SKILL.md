---
name: argo
license: MIT
description: Discover bounded Argo ocean profiles by region, time or float identifier, download exact official GDAC NetCDF files, and decode core pressure, temperature and practical salinity with data modes, quality flags, errors and provenance.
---

# Argo

Use Python 3.11+ and public HTTPS access to the Ifremer GDAC (or its official AWS index mirror). Discovery and download use the standard library; decoding requires `python -m pip install -r requirements.txt` in an isolated environment. Resolve scripts and references relative to this installed skill, regardless of the working directory. No account or credential is needed. This helper supports core per-cycle profile files, not BGC, trajectory or aggregate float files.

Establish the UTC interval, bounding box or WMO float identifier, requested measurements and intended use. Read [data access](references/data-access.md) for endpoints, cache contracts and limits. Use `scripts/argo.py index --output PATH.gz` to fetch one reusable index snapshot (`--source aws` explicitly selects the daily official mirror), then `discover --index PATH.gz --start YYYY-MM-DD --end YYYY-MM-DD --bbox WEST SOUTH EAST NORTH --limit 20`, or replace `--bbox` with `--wmo WMO`. End is exclusive. A west bound greater than east crosses the antimeridian. Limits bound returned records, not the full index scan. Results remain in index order, not nearest or newest order; choose a profile deliberately. An empty selection is not evidence that the ocean has no observations.

Download one exact returned `file` with `download --profile DAC/WMO/profiles/FILE.nc --output FILE.nc`. Profile IDs must retain DAC, WMO, cycle filename and direction; one file may contain multiple N_PROF records. R filenames can contain A-mode data: inspect NetCDF DATA_MODE, never infer processing solely from the filename. Decode with `decode --file FILE.nc > decoded.json`. See the [reproducible example](references/example.md).

Before interpreting measurements, read [interpretation](references/interpretation.md). For each core N_PROF record, R uses raw variables and matching QC; A/D use adjusted variables, matching adjusted QC and available errors. Missing adjusted data stay null; never silently substitute raw. Default accepted QC is 1; explicitly use `--qc 1,2` only when probably-good data fit the analysis. Masks and rejected observations remain null, with original QC and acceptance arrays retained. The helpers do not certify scientific fitness.

Retain source URL, retrieval time, SHA-256, index snapshot and selected file metadata alongside derived outputs. Pressure is not depth; practical salinity is not absolute salinity; profile locations are not precise underwater tracks. Check POSITION_QC and JULD_QC before mapping or temporal analysis. For combined temperature–salinity–pressure calculations, require a common accepted mask at the same profile and level. Do not pair independently compacted arrays.

Run offline checks with `python -m unittest discover -s tests -v` from the skill directory. No observations, caches or generated outputs belong in the installed skill. Data attribution and authoritative manuals are linked in the references; no upstream reader code is vendored.
