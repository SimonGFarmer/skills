# Bounded real-data examples

Run in a project/data directory outside the skill collection. Replace `/path/to/installed/usgs-earthquakes/scripts/usgs.py` below with the actual absolute path to the installed helper; the quoted command form works in a shell or PowerShell. Python 3.11+ is the only runtime dependency; `py -3.11` is an alternative on Windows when installed. JSON stdout includes the raw document/text and a response manifest; the hash is of the original response bytes, not the pretty-printed envelope. Historical values can be revised, so exact output hashes are not promised.

In Windows PowerShell 5.1, replace each `> FILE` with `| Out-File -Encoding utf8 FILE` to avoid its default UTF-16 redirection. The snippet below reads UTF-8 with or without a BOM. PowerShell 7 uses UTF-8 by default. See [Microsoft's encoding guidance](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_character_encoding).

Query one page of the Ridgecrest sequence (UTC, 100 km circle, M4+):

```sh
python "/path/to/installed/usgs-earthquakes/scripts/usgs.py" query --start 2019-07-06T00:00:00Z --end 2019-07-07T00:00:00Z --latitude 35.77 --longitude -117.60 --radius-km 100 --min-magnitude 4 --limit 100 > ridgecrest.json
```

Inspect returned `events`, `returned`, `count_at_preflight` and `has_more_at_preflight`. For a tiny pagination exercise use `--limit 2`, then repeat with `--offset 3`; stop after two pages and explicitly report four retrieved events rather than a complete sequence. Empty results mean no returned catalog matches, not no seismic activity.

Inspect the exact large Ridgecrest event and its preferred uncertainty fields:

```sh
python "/path/to/installed/usgs-earthquakes/scripts/usgs.py" detail --event-id ci38457511 > event.json
python "/path/to/installed/usgs-earthquakes/scripts/usgs.py" detail --event-id ci38457511 --format csv > event-uncertainty.json
```

Compare the two documents' IDs, origin times, update times and measurements before combining them. In `event.json`, find an active `origin` product with content key `quakeml.xml`. The following portable helper downloads that **exact discovered version**, keeping a manifest; it has a 2 MB budget and never executes downloaded material:

```python
import json
from pathlib import Path
import subprocess
import sys

helper = Path(sys.argv[1]).resolve()  # pass the installed helper's absolute path
event = json.loads(Path("event.json").read_text(encoding="utf-8-sig"))
products = [p for p in event["products"] if p["type"] == "origin"
            and p["status"] == "UPDATE" and p["preferred_in_response"]
            and "quakeml.xml" in p["contents"]]
if len(products) != 1:
    raise SystemExit("No unique preferred origin with QuakeML available")
product = products[0]
with Path("origin-manifest.json").open("w", encoding="utf-8") as manifest:
    subprocess.run([sys.executable, str(helper), "product", "--event-id", event["events"][0]["id"],
                    "--product-type", "origin", "--product-id", product["id"],
                    "--content", "quakeml.xml", "--output", "origin.xml", "--max-bytes", "2000000"],
                   stdout=manifest, check=True)
```

Save that snippet as `download_origin.py` in the project directory and run `python download_origin.py "/path/to/installed/usgs-earthquakes/scripts/usgs.py"` after creating `event.json`.

The same exact-version/content selection works for an available ShakeMap or DYFI file. Inspect actual content keys and advertised sizes first; do not default to a full raster ZIP. To interpret XML uncertainty, use a maintained QuakeML reader; the helper leaves original XML intact.

For a standard current snapshot:

```sh
python "/path/to/installed/usgs-earthquakes/scripts/usgs.py" feed --window day --level 4.5 > recent.json
```

Filter actual `event_type` and inspect `raw.metadata.generated`; this changes as the feed updates. A failure never substitutes the historical example.

Expected failures (exit 2 with JSON stderr): missing timezone (`query --start 2019-07-06 --end 2019-07-07`), illegal circle (`--latitude 91` with a complete circle), missing event (`detail --event-id no-such-usgs-event-000`), changed/unknown product ID or content key, a file already present, and a cap smaller than advertised content. In offline tests, simulated timeout/TLS/HTTP failures and truncated/oversized responses also remain failures.
