---
name: gaia-tap-data
license: MIT
description: Retrieve bounded Gaia DR3 sky fields from the official ESA TAP service and interpret astrometry, uncertainties and catalogue selection honestly.
---

# Gaia TAP data

Use this skill for small Gaia DR3 field retrievals and astrometric interpretation. Use `scripts/fetch_gaia.py` for a bounded anonymous cone search; it uses Python 3.10+ standard library only and the fixed ESA endpoint. Helper code and instructions are MIT licensed; [upstream data terms and attribution](NOTICE.md) remain separate. Read [references/data-contract.md](references/data-contract.md) before deriving quantities or comparing releases.

From a fresh copy of this folder, retrieve up to 100 bright field sources near the Pleiades:

```bash
python scripts/fetch_gaia.py --ra 56.75 --dec 24.12 --radius 0.1 --limit 100 --out gaia-field.json
```

This is a sky selection, not a cluster-membership catalogue. The result contains rows, actual query, selection/omission status, acquisition time, units and service provenance. Existing output files are refused. No credentials or additional packages are needed. The helper requires direct outbound HTTPS and does not implement proxy configuration.

Eligibility requires non-null `pmra` and `pmdec`, so this is the bright end of a proper-motion subset, not all sources in the cone. The helper accepts UTF-8 VOTable TABLEDATA only and rejects other encodings, binary serialization and DTD/entity declarations.

Keep retrieval bounds explicit: radius >0 and <=1 degree, rows 1–1000, request I/O deadline <=30 seconds, response <=8 MiB. OS DNS resolution may exceed that deadline; an external process deadline is needed when a hard wall-clock cap is required. The script requests one extra row and reports omitted matches; `TOP` selects the bright end, not a representative or complete sample. Errors fail without a fabricated or stale substitute. Retry deliberately after inspecting the failure; there is no automatic retry or mirror fallback.

Preserve decimal-string source IDs and null measurements. Gaia `pmra` already equals `mu_alpha * cos(dec)`; do not apply cosine again. Separate catalogue measurements from any modelled position, distance or velocity. Linear motion projections are approximations, not observed history, Galactic orbits or guaranteed predictions. Missing radial velocity is not zero. Negative parallax is not negative distance. Never infer temperature directly from BP–RP.

For uncertainty propagation use the published errors and correlations together, and state assumptions and systematic-error omissions. RUWE is a fit diagnostic; describe any selected cut instead of treating it as universal quality certification. Do not identify sources across releases by equal IDs alone.

Run meaningful offline checks with:

```bash
python -m unittest discover -s tests -v
```

Before claiming operational success, run the exact retrieval command above from a fresh installation and inspect the returned receipt and rows. Offline tests do not prove live endpoint compatibility. Larger/long-running jobs require ESA asynchronous TAP and explicit additional access tooling; do not expand this helper into an unbounded catalogue download.

Official sources: [DR3 data model](https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_main_source_catalogue/ssec_dm_gaia_source.html), [archive extraction guidance](https://www.cosmos.esa.int/web/gaia-users/archive/extract-data), [Gaia data credits](https://www.cosmos.esa.int/web/gaia-users/credits).
