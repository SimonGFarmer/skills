# Data access

Official sources:
- [ADMT data access](https://www.argodatamgt.org/DataAccess.html): GDAC HTTPS endpoints, data organization, NetCDF and CSV indexes
- [Ifremer GDAC](https://data-argo.ifremer.fr/): the helper's default index and profile origin
- [Argo format manual](https://oneargo.github.io/argo-format-user-manual/), also [manual DOI](https://doi.org/10.13155/29825)
- [Official AWS GDAC registry](https://registry.opendata.aws/argo-gdac-marinedata/): daily mirror, anonymous access
- [Argo data DOI](https://doi.org/10.17882/42182): citation and snapshot information
- [Argo acknowledgement](https://argo.ucsd.edu/data/acknowledging-argo/)

The compressed core index is `https://data-argo.ifremer.fr/ar_index_global_prof.txt.gz`. Comment-prefixed metadata precede CSV columns including file, date, latitude, longitude, ocean, profiler_type, institution and date_update. Index date is the profile date; date_update is publication/update metadata. Rows are not sorted by proximity or recency. File paths are relative to `https://data-argo.ifremer.fr/dac/`; the helper accepts only core per-cycle R/D paths and never arbitrary URLs or path traversal. Core indexes omit BGC-specific variables and are not complete inventories of every Argo product.

An explicit `index --source aws` uses `https://argo-gdac-sandbox.s3.eu-west-3.amazonaws.com/pub/idx/ar_index_global_prof.txt.gz`. This is the daily-updated public bucket linked by ADMT and the AWS registry; it can lag Ifremer. No credentials are required. Source selection is explicit, never a silent fallback. Profile downloads still come from Ifremer; retain both index and profile provenance because the snapshots can differ.

A full compressed index is tens of MB and grows over time. Fetch once, reuse locally for region and WMO searches, and deliberately choose a fresh output path when a new snapshot is needed. The default index cap is 120 MB; individual profile downloads cap at 20 MB. These are helper safeguards, not published provider quotas. No numerical GDAC request-rate limit was established from the cited official access page. Use serial bounded requests, cache, avoid repeated full-index downloads, and stop or back off on 429/503. Helpers perform no automatic retries or parallel requests; timeout is 60 seconds per blocking network operation, not a total wall-clock limit. Download caps can be explicitly changed with `--max-bytes`.

Discovery scans the complete local index and returns at most 1,000 records. Its `matches`, `returned` and `truncated` fields disclose selection truncation. At large scale, use official snapshot/synchronization guidance rather than expanding this small helper into an unbounded crawler. Missing coordinates are omitted from region searches but can appear in WMO searches. The date interval is inclusive/exclusive UTC midnight; index selection cannot filter individual subsurface sample times.

Downloads create a data file plus `.json` provenance sidecar. Existing complete entries are reused only when URL, byte count and SHA-256 agree. Incomplete or mismatching entries fail; inspect them and choose another path rather than overwriting. SHA-256 verifies local cache consistency, not an independently signed provider checksum. If interrupted, leftover partial sidecars must be inspected/removed before reusing that destination. Current GDAC contents are mutable; pin local bytes and hashes for reproducibility. Download NetCDF bytes are not geographically cropped.

Dependencies: netCDF4-python and NumPy retain their upstream licenses; no code from these projects is bundled. Consult [netCDF4-python](https://github.com/Unidata/netcdf4-python) and [NumPy](https://numpy.org/). This package does not grant a data license; use the current dataset citation and terms at the official DOI. Helper code and instructions are MIT licensed, copyright 2026 Simon G Farmer; see the included LICENSE.
