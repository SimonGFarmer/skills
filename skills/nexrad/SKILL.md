---
name: nexrad
description: Find NEXRAD radar stations, discover and download bounded recent or historical Archive II observations, decode measured radar fields and coordinates, and build radar analyses or applications from NOAA data.
license: MIT
---

# NEXRAD

Use this skill for measured weather radar data. Establish location/station, UTC interval, requested fields and output before choosing observations. Find nearby stations with `scripts/stations.py --lat LAT --lon LON`; distance is geographic proximity, not a guarantee of coverage or operational status.

Use Python 3.11 and network access for station lookup and archive discovery/download. Resolve all helper paths relative to this installed skill directory, regardless of the working directory. Discovery uses only Python's standard library. For decoding create a project virtual environment with `python3.11 -m venv .venv` (Windows: `py -3.11 -m venv .venv`), then run that environment's Python with `-m pip install -r /absolute/path/to/nexrad/scripts/requirements.txt`. See [references/example.md](references/example.md) for executable setup and usage.

Read [references/data-access.md](references/data-access.md) for source contracts and historical/recent selection. Run `scripts/archive.py --station KTLX --start 2024-05-06T00:00:00Z --end 2024-05-06T00:10:00Z` to return JSON. Add `--download OUTPUT --max-files 1 --max-bytes 50000000` to download the earliest selected observation. Adjust caps deliberately for the request. The helper supports up to seven days per discovery; split larger intervals. It lists complete archive objects, not live chunks. Empty results are not clear weather.

Run `scripts/decode.py FILE --npz OUTPUT.npz` with the decoding environment's Python. JSON reports available fields, units, dimensions, masks and time origin. NPZ preserves reader arrays, masks, ray times, sweep boundaries and coordinates. Read [references/decoded-data.md](references/decoded-data.md) before using the output in analyses or applications. Enumerate actual fields; never promise moments absent from a particular volume. This helper delegates parsing to Py-ART, not a homegrown full-format decoder.

Use [references/example.md](references/example.md) for a tiny real-data workflow. Build the requested analysis or app around these outputs: retain provenance, units, timestamp meaning and missing masks; make any interpolation, gridding, filtering or visual thresholds explicit. Slant range and beam height do not equal surface distance or terrain clearance. Reflectivity is not visible cloud density; velocity is radial, not a complete wind vector. Consult official warnings for hazardous-weather decisions.
