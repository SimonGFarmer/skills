# Reader and output contract

The helper uses [Py-ART read_nexrad_archive](https://arm-doe.github.io/pyart/API/generated/pyart.io.read_nexrad_archive.html), pinned to arm-pyart 2.2.4, and returns a [Radar object](https://arm-doe.github.io/pyart/API/generated/pyart.core.Radar.html). Upstream supports Archive II message types 1 and 31, bzip2-compressed or uncompressed archives and gzip-wrapped files. It does not imply support for all historical variants, corrupted archives, live chunks or Level III. Check upstream warnings and fail explicitly when a file cannot be parsed. Some reader behavior, including native range resolution alignment, is upstream processing; this is not byte-for-byte raw code export. Do not imply independent full Level II conformance testing.

Py-ART's conventional field names include `reflectivity`, `velocity`, `spectrum_width`, `differential_reflectivity`, `differential_phase`, `cross_correlation_ratio`; actual presence and units come from `radar.fields`. Neither field presence nor range is fixed across scans. The JSON reports only fields actually read, with shape, units, valid/masked counts and valid extrema. The helper uses upstream `linear_interp=True`: mixed-resolution rays can be linearly interpolated between valid gate pairs onto the reader's common range grid. Preserve stderr warnings; do not label those values untouched native samples. For exact per-moment raw gate geometry, inspect upstream `NEXRADLevel2File` APIs and validate a separate export.

NPZ keys:

| Array | Meaning |
| --- | --- |
| each field and `FIELD__mask` | rays × gates; float values, invalids filled NaN; Boolean True means invalid |
| `range` | gate center slant distance, meters |
| `azimuth`, `elevation`, `fixed_angle` | degrees; ray and sweep angles |
| `time` | per-ray offsets; combine with JSON `time_units` origin |
| `sweep_start_ray_index`, `sweep_end_ray_index` | inclusive ray bounds in acquisition order |
| `latitude`, `longitude`, `altitude` | radar location, degrees and meters from reader |
| `gate_x`, `gate_y`, `gate_z` | east, north, up in meters relative to radar, Py-ART beam model |
| `gate_latitude`, `gate_longitude`, `gate_altitude` | reader-derived gate location, degrees and meters |

Py-ART combines invalid/no-data and range-folded codes into masked data for this reader: exported masks do not distinguish their reasons. Preserve invalid values, never convert them to measured zero. The export also masks nonfinite values. Coordinates use Py-ART's approximate effective-Earth-radius geometry; gate altitude is not height above terrain, and altitude datum must be assessed before combining with DEMs. Range/angle grids can contain masked padding and upstream resolution alignment; use masks for each field separately. Repeated/split sweeps stay in acquisition order; don't merge by elevation alone.

For a derived grid use upstream [grid_from_radars](https://arm-doe.github.io/pyart/API/generated/pyart.map.grid_from_radars.html) with explicit domain/resolution and document interpolation. For applications, prefer native sweep subsets or bounded derived outputs; the full coordinate NPZ can be much larger than the source file. Visualization thresholds belong to the requested app. Export is an analysis intermediate, not CF-compliant NetCDF; use upstream writers for interoperable formats.
