# One historical volume

Use Python 3.11. From your analysis directory, create an isolated environment:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r /absolute/path/to/nexrad/scripts/requirements.txt
```

On Windows, use `py -3.11 -m venv .venv` and `.venv\Scripts\python.exe` instead. Replace the requirements path with the installed skill's absolute path; quote paths containing spaces.

Save this as `example.py`, set `skill` to the installed skill directory, and run it with the environment's Python. It downloads at most one 50 MB observation and uses the returned filename rather than assuming an archive key:

```python
import json
from pathlib import Path
import subprocess
import sys

skill = Path('/absolute/path/to/nexrad')
def helper(name, *args):
    result = subprocess.run(
        [sys.executable, str(skill / 'scripts' / name), *args],
        capture_output=True, text=True,
    )
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    result.check_returncode()
    return json.loads(result.stdout)

manifest = helper('archive.py', '--station', 'KTLX',
    '--start', '2024-05-06T00:00:00Z', '--end', '2024-05-06T00:10:00Z',
    '--download', 'radar-data', '--max-files', '1', '--max-bytes', '50000000')
Path('manifest.json').write_text(json.dumps(manifest, indent=2))
if not manifest['observations']:
    raise RuntimeError('No archive observations found in this interval')
summary = helper('decode.py', manifest['observations'][0]['local_path'])
Path('summary.json').write_text(json.dumps(summary, indent=2))
print(json.dumps(summary['fields'], indent=2))
```

The historical window contains real data; availability is external. JSON field summaries already report valid extrema, so no array export is needed to answer a maximum-value question. To analyze gates, add `--npz volume.npz` to the decode arguments. Full coordinate exports can be hundreds of MB and require substantially more RAM than the compressed archive.

```python
import numpy as np
with np.load('volume.npz', allow_pickle=False) as volume:
    values = np.ma.array(volume['reflectivity'], mask=volume['reflectivity__mask'])
    print(float(values.max()) if values.count() else None)
```

This is a volume maximum over valid gates, not rainfall, tornado detection or a surface observation. For recent data, compute the window at execution time:

```python
from datetime import datetime, timedelta, timezone
end = datetime.now(timezone.utc)
start = end - timedelta(hours=2)
recent = helper('archive.py', '--station', 'KTLX',
    '--start', start.isoformat(), '--end', end.isoformat())
print(json.dumps(recent, indent=2))
```

Discovery lists observations in ascending key time. To download, add the same explicit file/byte caps and a fresh output directory. A recent scan is the result of the current UTC query, not a reused historical filename.
