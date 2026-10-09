# Data contract and interpretation

## Files and provenance

`search` writes `search.response.json` (unchanged response bytes; empty for HTTP 204) and `search.manifest.json`. `entry` writes `<accession>.entry.json`, `<accession>.cif` and `<accession>.manifest.json`. A manifest includes requested URL, HTTP status, UTC retrieval timestamp, byte count, raw SHA-256, ETag/Last-Modified when supplied, input accession/query, scope and a small metadata summary. Raw source responses remain authoritative. The helper does not calculate a scientific measurement.

The metadata summary preserves JSON nulls and labels absent paths separately in `missing_fields`; it neither replaces unknowns with zero nor invents defaults. `rcsb_accession_info` and `pdbx_audit_revision_history` are retained whole when present. Initial release, deposition and revision dates have different meanings. A latest-file URL is mutable; a hash identifies the saved bytes, not a guaranteed stable remote revision. The raw CIF audit trail is not parsed by this helper.

The entry metadata must explicitly report `rcsb_entry_info.structure_determination_methodology = experimental`; missing, integrative or computational methodology fails closed. Search uses this same predicate together with `results_content_type = [experimental]`. This scope is deliberate; use a separate, clearly labeled workflow for predicted or integrative models.

## Schema, units and QC

| Source item | Meaning and precautions |
| --- | --- |
| `struct.title`, `exptl[*].method` | Deposited title and experimental method list, retained in raw metadata. |
| `rcsb_entry_info.resolution_combined` | Reported resolution value list in angstroms when applicable; a missing value is not zero or poor quality. Methods differ and values need method-aware interpretation. |
| `rcsb_accession_info`, `pdbx_audit_revision_history` | Release/revision provenance; retain all fields and check against downloaded CIF. |
| `_atom_site.Cartn_x`, `Cartn_y`, `Cartn_z` | Cartesian coordinates in angstroms in the deposited frame, not geographic coordinates. |
| `_atom_site.occupancy` | Dimensionless site occupancy; missing is not 1. Alternate conformers require an explicit selection policy. |
| `_atom_site.B_iso_or_equiv` | Isotropic/equivalent displacement parameter; the B convention has angstrom-squared dimensions and relates to U by B = 8 pi squared U. Check `_refine.pdbx_adp_type` for the reported convention. It is not pLDDT or a probability. |
| `_atom_site.pdbx_PDB_model_num` | Model identity; multiple NMR models are an ensemble, not a temporal trajectory. |
| `_atom_site.label_*`, `_atom_site.auth_*` | Distinct archive and author identifiers; retain both, plus insertion code and alternate-location ID. |
| `_pdbx_struct_assembly*`, `_pdbx_struct_oper_list` | Assembly descriptions/operators; the deposited coordinate set must not be silently called the biological assembly. |

CIF `?` means unknown and `.` means not applicable; preserve that distinction in any parser output. Validate models, atom selections and finite coordinates before calculating distances. Missing residues and unobserved atoms are absent evidence, not coordinates to interpolate. Do not infer chemical bonds solely from drawing proximity. If filtering waters, ligands, hydrogens or conformers, disclose it with counts and selection rules.

Read the [PDBx/mmCIF user guide](https://mmcif.wwpdb.org/docs/user-guide/guide.html), [RCSB entry schema](https://data.rcsb.org/rest/v1/schema/entry), [coordinate dictionary](https://mmcif.wwpdb.org/dictionaries/mmcif_pdbx_v50.dic/Items/_atom_site.Cartn_x.html), [occupancy dictionary](https://mmcif.wwpdb.org/dictionaries/mmcif_pdbx_v50.dic/Items/_atom_site.occupancy.html), [B-factor dictionary](https://mmcif.wwpdb.org/dictionaries/mmcif_pdbx_v50.dic/Items/_atom_site.B_iso_or_equiv.html) and [wwPDB validation resources](https://www.wwpdb.org/validation/validation-reports) for the selected method. Use validation reports to assess model quality; a successful HTTP response alone does not establish validity. Cite the accession and original structure publication where available, following [RCSB citation policies](https://www.rcsb.org/pages/policies). The archive's data terms and any integrated external annotations are distinct from the license of analysis code.

## Historical discovery

The [wwPDB versioned archive](https://www.wwpdb.org/ftp/pdb-versioned-ftp-site) distributes major coordinate versions, with an archive introduced in 2017; do not assume all historical minor revisions or all pre-2017 bytes are recoverable. Major increments reflect changes to coordinates, polymer sequence or chemical description; other metadata changes are minor.

1. Record the accession and current CIF revision audit categories. Map a classic accession such as `1abc` to `pdb_00001abc`; keep an extended accession intact.
2. Consult the official versioned-archive page and its current mirror links. Discover available filenames for that entry before selecting an actual major/minor version. The documented entry grouping uses the two penultimate ID characters (for `pdb_00001abc`, `ab`).
3. Identify the explicit coordinate filename and version, retrieve with byte/time bounds using a reviewed downloader, and save the URL, retrieval time, compressed and decompressed hashes, revision trail and chosen version. This helper supplies no historical downloader.
4. For an as-of-date request, compare recorded release/revision dates with available versions. Explain any unavailable revision or coverage gap; current metadata cannot silently stand in for historical metadata.

Extended identifiers are `pdb_` plus eight alphanumerics, documented in the [wwPDB ID FAQ](https://www.wwpdb.org/documentation/pdb-id-extension-faq). Consult [current archive transition guidance](https://www.wwpdb.org/documentation/new-format-for-pdb-ids) when choosing paths. Retain full IDs in output and citations.
