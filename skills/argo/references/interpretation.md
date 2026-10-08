# Measurement interpretation

Use the [official profile guidance](https://argo.ucsd.edu/data/how-to-use-argo-files/) and [format manual](https://oneargo.github.io/argo-format-user-manual/) for the exact product. The helper preserves N_PROF and N_LEVELS rather than assuming one profile per file.

Core DATA_MODE applies per N_PROF: R selects PRES/TEMP/PSAL and their _QC fields. A and D select _ADJUSTED and _ADJUSTED_QC; _ADJUSTED_ERROR is preserved when present. R means real time; A means adjusted in real time; D means delayed mode. A/D flags do not guarantee all values are usable. Missing adjusted variables fail; fill-valued adjusted measurements stay missing. The helper never substitutes raw data. Missing error is null, not zero uncertainty. Errors are reported per original level, including levels rejected by QC; apply the accepted mask when using them.

Quality 1 is good; 2 is probably good. Flags 0 (not QC'd), 3 (potentially correctable bad), 4 (bad), 9 (missing), blanks and other flags are excluded by this helper. Its default is strictly 1, with optional 1,2. Retain the chosen policy in reports. Check time/location QC separately: they are preserved but not automatically used to discard profiles. NetCDF fill values and non-finite numeric values become JSON null. A null measurement may mean missing or rejected QC; the QC and accepted arrays distinguish those cases.

The file's units are authoritative. PRES is typically decibar, TEMP degree Celsius (ITS-90), PSAL practical salinity (PSS-78; commonly labelled psu). Pressure is not geometric depth. Converting pressure to depth requires latitude and an appropriate seawater formulation; practical and absolute salinity also differ. The helper performs no such conversions. JULD retains its numeric value and units (typically days since 1950-01-01 UTC); do not interpret it as Unix time.

A profile's latitude/longitude represents a reported profile position and may be estimated. It is not a resolved location for every underwater sample. Connecting successive positions visualizes profile locations, not the float's exact underwater trajectory. Use trajectory products and their own QC/time conventions for trajectory questions.

For scientific work sensitive to small pressure biases, [Argo's data FAQ](https://argo.ucsd.edu/data/data-faq/) recommends delayed-mode adjusted data, QC 1, and rejecting pressure adjusted errors greater than 20 dbar. That additional criterion is not applied automatically here. State any additional selection and uncertainty treatment; real-time salinity can have sensor drift.

BGC needs PARAMETER_DATA_MODE, matched to STATION_PARAMETERS for each profile/parameter, rather than core DATA_MODE alone. Non-experts should use adjusted BGC data. This core helper does not decode BGC files, dissolved oxygen or chlorophyll; use the official BGC/Sprof data models and parameter-specific QC, units and adjustment guidance instead of adapting core assumptions silently.
