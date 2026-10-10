# Data contract and limits

The helper queries `gaiadr3.gaia_source` at `https://gea.esac.esa.int/tap-server/tap/sync`. Gaia DR3 astrometry uses ICRS at reference epoch J2016.0, expressed in Julian years of TCB. DR3 is a catalogue, not a live star tracker. Pin the release in provenance; review the [official release scenario](https://www.cosmos.esa.int/web/gaia/release) before selecting a newer release.

| Columns | Meaning / units |
| --- | --- |
| source_id | Decimal string; unique within a release, potentially changes between releases |
| ref_epoch | Julian year, TCB; use the returned value |
| ra, dec | Barycentric ICRS angles, degrees |
| ra_error, dec_error, parallax, parallax_error | mas; RA error is sigma(alpha) cos(dec) |
| pmra, pmdec, pmra_error, pmdec_error | mas/year; pmra is mu(alpha) cos(dec) |
| ten *_corr columns | Dimensionless correlations of the five fitted astrometric parameters |
| phot_g_mean_mag | Mean G magnitude, not flux or luminosity |
| bp_rp | BP minus RP magnitude; colour affected by extinction and other effects |
| ruwe | Dimensionless renormalised fit statistic |
| astrometric_params_solved | 3: positions only; 31: five parameters; 95: six parameters including pseudocolour |

The output contains expected units from this contract and separately retains service-reported FIELD units and datatypes. Present units must match supported DR3 spellings; missing units stay explicitly missing in reported metadata. The parser rejects malformed/nonfinite numbers, out-of-range correlations, negative standard errors and invalid coordinates. It preserves empty optional cells and explicit FIELD VALUES null sentinels as JSON null; scientific suitability still needs task-specific review. The ten correlation values reconstruct the five-parameter formal covariance via `C[i,j] = corr[i,j] * sigma[i] * sigma[j]` with diagonal `sigma[i]**2`, using the alpha-star convention. These formal uncertainties do not include every systematic effect. For six-parameter solutions this helper omits pseudocolour and its additional covariance terms.

Do not convert all parallaxes to `1000/parallax` pc. Weak/negative parallaxes contain information and distance inference requires a statistical model, uncertainty and systematic-error treatment. A high signal-to-noise reciprocal may be an explicitly labelled approximation for a suitable individual source; do not portray it as a general Gaia distance measurement. Use [Gaia collaboration guidance](https://arxiv.org/abs/1804.09376) and the [DR3 known issues](https://www.cosmos.esa.int/web/gaia/dr3-known-issues) for scientific interpretation.

RA wrap, polar coordinates and source epoch matter when propagating or cross-matching. A tangent-plane motion vector has components pmra and pmdec. The small-angle RA increment divides pmra by cos(dec), with conversion from mas to degrees; that approximation becomes fragile near a pole and for large displacements. For precision work use documented epoch propagation with appropriate radial-velocity/distance assumptions, not an invented long-term trajectory. Previous releases are independent reductions; use official neighbourhood cross-match tables and inspect ambiguous matches.

Service limits can change; consult the [current ESA extraction guidance](https://www.cosmos.esa.int/web/gaia-users/archive/extract-data) before larger jobs. This helper's fixed local caps are at most 1001 requested rows, 8 MiB received XML and a 30-second socket-I/O deadline. It uses synchronous TAP only; anonymous asynchronous jobs require expiry and lifecycle management that this helper does not provide.

`TOP N` bounds the selected query. `MAXREC` bounds returned output and can produce overflow. Absence of overflow does not prove completeness of the sky selection. The extra row detects omission caused by this helper's display limit. VOTable QUERY_STATUS may contain a trailing ERROR or OVERFLOW after an initial OK; all are checked. Overflow is reported as incomplete data, and any ERROR fails the retrieval. See [TAP 1.1](https://www.ivoa.net/documents/TAP/20190927/REC-TAP-1.1.html) and [DALI 1.1](https://www.ivoa.net/documents/DALI/20170517/REC-DALI-1.1.html).

The helper requests ESA `votable_plain`, accepts TABLEDATA XML only, rejects compressed responses, DTD/entity declarations and other VOTable serializations, and permits at most two redirects within the same HTTPS host and `/tap-server/` path. Unsupported serialization fails explicitly. Response byte limits apply to received XML. The monotonic deadline covers request socket I/O; OS DNS resolution can exceed it. A supervising process is needed for a strict wall-clock cap. Limits and receipt do not establish population completeness, membership or scientific reliability.

When publishing analysis, include the Gaia acknowledgement and appropriate release papers from [ESA's credits page](https://www.cosmos.esa.int/web/gaia-users/credits). Dataset attribution does not select a software licence.
