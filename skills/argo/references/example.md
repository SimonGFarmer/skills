# Reproducible bounded example

Run from the installed skill folder, with outputs in a separate working directory. On Windows, use suitable native paths and `py -3.11` if needed. Set WORK to an existing scratch directory; these POSIX commands assume `$WORK` is set.

```sh
python -m pip install -r requirements.txt
python scripts/argo.py index --source aws --output "$WORK/core-index.txt.gz"
python scripts/argo.py discover --index "$WORK/core-index.txt.gz" --start 2000-01-01 --end 2005-01-01 --wmo 1900050 --limit 3 > "$WORK/selection.json"
python scripts/argo.py download --profile aoml/1900050/profiles/D1900050_001.nc --output "$WORK/D1900050_001.nc"
python scripts/argo.py decode --file "$WORK/D1900050_001.nc" > "$WORK/decoded.json"
```

This example explicitly uses the daily official AWS index mirror; omit `--source aws` for the primary Ifremer index. Both choices preserve source provenance.

The exact historical profile is a bounded decoding example, independent of which three discovery rows are returned. Verify its WMO/cycle, DATA_MODE, units, QC and valid-level counts from the decoded output; do not hard-code measurement values or assume archive bytes never change. For a region query, replace WMO with `--bbox -70 20 -40 40` and a relevant bounded interval. For an antimeridian-spanning region use west > east, e.g. `--bbox 170 -20 -170 20`.

Report temperature and practical salinity against pressure with units and accepted-QC policy, distinguishing missing data from invalid data and preserving errors/provenance. Do not describe a pressure axis in metres or a profile-location line as a precise float track. Reusing the exact download path verifies and reuses local cached bytes; use a new path to request a fresh archive version.
