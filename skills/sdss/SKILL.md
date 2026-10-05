---
name: sdss
description: Query official SDSS DR20 spectral records by sky region or exact target identifier, retrieve available spectra, and interpret classifications, redshifts and legacy photometry with their release provenance and quality flags.
license: MIT
---

# SDSS

Use Python 3.11 or later and HTTPS access to `skyserver.sdss.org`, the SDSS Science Archive Server and `api.sdss.org` for Valis delivery. The helper uses only the Python standard library; no credentials or website are required for these public interfaces. Resolve `scripts/sdss.py` relative to this installed skill folder, regardless of the working directory. On Windows, `py -3.11` can replace `python` in the examples.

Establish ICRS RA/Dec in decimal degrees and radius in arcminutes, or an exact identifier with its namespace. If given a name, resolve and verify its coordinates with an authoritative astronomy resolver first; this helper does not resolve names. Read [references/data-access.md](references/data-access.md) for source contracts, supported parameter joins and bounds.

Run `python scripts/sdss.py cone --ra 229.525575753922 --dec 42.7458537608544 --radius 2` for DR20 ALLSPEC records, or `target --id-type sdss_id --id ID` for a target's records. `allspec_id` is an alphanumeric record identifier; `sdss_id` identifies a cross-matched target; `specobjid` identifies a pipeline spectrum. Preserve every identifier as a string. A target may have several observations and products. Results are ordered by ID, not distance. If `has_more` is true, repeat the identical query with `--after NEXT_AFTER`; retain all pages and report any stopping cap. Empty results mean no returned records in that query, not an empty sky or absent archive data.

Use `photo-cone` for DR17 primary imaging measurements in the r band, or `photo-id --id OBJID` for an exact photometric record (retain its mode). The photometric `specobjid` is an exact legacy spectrum association when present; do not attach a nearby DR20 spectrum as though it were that association. Point-like/extended morphology is not confirmed STAR/GALAXY. Do not derive photometry or object class from RGB imagery. DR20 has no new SDSS imaging; any SDSS DR9 color HiPS background remains DR9.

Read [references/interpretation.md](references/interpretation.md) before reporting measurements. Preserve class, subclass, z, z_err, zwarning, instrument, run2d, coadd and both catalog/archive provenance. Missing fields, empty strings and survey sentinel values are unavailable measurements. `pipeline_redshift_unflagged` means only a finite z and zero warning; it is not a guarantee. SDSS recommends its visually inspected BHM catalog for robust classification/redshift work; this helper does not load that catalog. Do not turn stellar z into cosmological distance or calculate lookback time without explicit cosmology and justified redshift quality.

Retrieve one exact record with `spectrum --id ALLSPEC_ID --output spectrum.fits > spectrum.json`. For DR20 BOSS v6_2_1 daily lite products, add `--delivery valis` to use the official file service; it first verifies that Valis resolves the exact catalog archive path. Other products use the default `--delivery sas`. Inspect available records before choosing an observation/product; do not assume every imaged target has a spectrum. Downloads preserve original FITS bytes and report catalog/archive provenance, delivery URL, full record and SHA-256. A missing or unsupported URL, service failure or size limit must be reported as such; no automatic fallback or insecure transport is used. This helper does not decode every instrument; use the file's official data model and a maintained FITS reader for analysis. Optical units, masks and uncertainty caveats are in [references/interpretation.md](references/interpretation.md).

See [references/example.md](references/example.md) for a real region, exact legacy association and a new DR20 spectrum. Retain machine-readable output alongside analyses. Check [NOTICE.md](NOTICE.md) for authorship and survey attribution.
