---
name: satellite-stac-data
description: Discover bounded Landsat and Sentinel-2 acquisitions through the public Planetary Computer STAC API, preserve provenance, and obtain reproducible display-preview links. Use for historical satellite imagery discovery; calibrated raster analysis requires a separate COG and quality-mask workflow.
---

# Satellite acquisition discovery

Use `scripts/search_stac.py` with Python 3.10+; discovery needs only the standard library and no account, API key, or persistent credentials. Resolve script paths relative to this skill directory.

Choose a geographic region, collection and explicit acquisition interval before searching. The helper accepts `landsat-c2-l2` or `sentinel-2-l2a`, a region up to 2 degrees wide/high within ±75 degrees latitude, and an interval up to 366 days. It fetches one page per invocation, up to 40 items per page and five pages per search. These are tool bounds, not provider coverage limits. Split larger questions into deliberate bounded searches.

```sh
python scripts/search_stac.py --collection landsat-c2-l2 --bbox 12.4 41.8 12.6 42.0 --start 2024-06-01 --end 2024-08-31 --cloud 30 --limit 20 --page-limit 3 --output rome-page1.json
python -m unittest discover -s tests -v
```

Coordinates are WGS84 longitude/latitude degrees, in west, south, east, north order. Dates and acquisition timestamps are UTC. The example searches summer 2024 scenes intersecting central Rome; it does not promise a fixed result count or clear pixels. The cloud filter can exclude acquisitions with unknown scene cloud cover. Continue only when the output contains a non-null `continuation`; do not imply the first page exhausts the archive. Empty results are a valid outcome. On HTTP 429, honor Retry-After and wait before a deliberate retry; the helper does not automatically retry.

When a continuation is present, fetch one further page explicitly:

```sh
python scripts/search_stac.py --continue-from rome-page1.json --output rome-page2.json
```

The default response bound is 8 MiB. Network operations have a 30-second socket timeout and deadline checks between reads; a blocking read can extend beyond that deadline. Output paths must be new files; existing files are not overwritten.

Output contains the original STAC items and links, a compact `summary`, acquisition query, retrieval UTC time, and continuation state. `cloud_cover` remains null when unknown. Scene cloud percentage describes the whole acquisition, not the selected region. Collection temporal extent likewise does not establish local coverage. Save item IDs, timestamps, collection and render URLs with any derived presentation. Asset SAS query parameters are removed before output; pagination tokens are opaque cursors, not asset credentials.

Use the item's `rendered_preview` link for a provider-rendered overview. The helper also supplies a fixed-size `bbox_preview` URL when the item has a compatible official TileJSON link: it preserves the provider's display parameters and requests a shared EPSG:4326 grid with nearest sampling and a nodata mask. It generates links, not downloaded images. Inspect successful image responses and actual missing coverage before presenting a comparison. Matching output grids do not establish feature registration. Preserve cloud, shadow and nodata honestly; do not interpolate observations or infer quantitative change from stretched RGB.

The default 512 by 512 preview dimensions describe display pixels, not the source's native ground resolution. Enlarging an existing image adds no measured detail; a higher-resolution render cannot create detail beyond the native data. Rendered alpha describes display coverage; opaque pixels do not establish complete native band data, pixel-level cloud quality or a cloudless acquisition.

For calibrated windows, indices or pixel-level cloud QA, read [scientific-access.md](references/scientific-access.md). This helper does not implement numerical raster analysis or COG signing.

Official access references: [STAC quickstart](https://github.com/microsoft/PlanetaryComputerExamples/blob/main/quickstarts/reading-stac.ipynb), [Landsat collection](https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l2), [Sentinel-2 collection](https://planetarycomputer.microsoft.com/api/stac/v1/collections/sentinel-2-l2a), [display API schema](https://planetarycomputer.microsoft.com/api/data/v1/openapi.json).

Credit NASA/USGS Landsat and Microsoft hosting. For processed Sentinel imagery, include `Contains modified Copernicus Sentinel data [acquisition year]` and Microsoft hosting. Preserve collection citation/license links; dataset terms do not select a license for new code. [USGS citation](https://www.usgs.gov/centers/eros/data-citation), [Copernicus citation](https://documentation.dataspace.copernicus.eu/FAQ.html).
