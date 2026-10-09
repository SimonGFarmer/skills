---
name: pdb-archive-data
license: MIT
description: Discover experimental PDB structures and retrieve bounded RCSB entry metadata and original mmCIF files with provenance for reproducible structural analysis.
---

# PDB archive data

Use Python 3.10+ and `scripts/pdb_access.py` for small, explicit reads from the official RCSB services. No account or third-party Python dependency is needed for retrieval. Helper code and instructions are MIT licensed; [data terms and attribution](NOTICE.md) are separate. Read [references/data-contract.md](references/data-contract.md) before interpreting coordinates, quality, assemblies, or revisions.

## Discover and retrieve

Search is an entry-level annotation search, explicitly restricted to experimental methodology. Inspect metadata to decide whether a hit answers the scientific question; a text hit does not establish a biological relationship. Each invocation requests one page; results can change between pages.

From this skill's directory, these exact commands create separate output directories:

```sh
python scripts/pdb_access.py search --text crambin --rows 5 --page 1 --out crambin-search
python scripts/pdb_access.py entry 1CRN --out crambin-entry
python -m unittest discover -s tests -v
```

The example searches for candidate crambin entries, then independently retrieves the specified accession; it does not assume a particular search ranking. Output metadata and coordinates are separate server responses, not an atomic archive snapshot. Inspect their recorded retrieval times, revision metadata and mmCIF audit categories for agreement before combining them. Retain the raw files and manifests alongside any derived results.

Search accepts optional `--method "X-RAY DIFFRACTION"`, `--released-after YYYY-MM-DD`, and `--released-before YYYY-MM-DD`. Dates filter initial release date inclusively, not experiment date or historical archive state. It allows 1–100 rows and pages 1–5; reaching a page cap is reported. Entry accepts a four-character accession or `pdb_` plus eight alphanumeric characters. Errors stop the operation; there is no format, mirror, synthetic-data or metadata fallback. Do not infer that a syntactically valid accession exists.

## Scientific use

For existing entries, the defined `pdb_0000` alias is mapped to its four-character accession for current RCSB endpoints; both requested and service accessions are recorded. Other extended IDs are retained intact. Endpoint support for newly issued extended IDs must be rechecked as the archive transition proceeds; no alternate endpoint is guessed after a failure.

The script saves the deposited coordinate file intact; it does not generate an assembly, infer bonds, select conformers, or parse a subset of CIF syntax. For analysis use a mature parser, such as [Gemmi's CIF API](https://gemmi.readthedocs.io/en/latest/cif.html) and [structure API](https://gemmi.readthedocs.io/en/latest/mol.html), as an optional dependency; record its installed version and your model/chain/alternate-location selection. Preserve missing values and distinguish author identifiers from label identifiers.

Represent deposited geometry as a model informed by experiment. Never present B factors as confidence probabilities, NMR models as time frames, or camera animation as molecular dynamics. Read method-specific validation and experimental evidence before making a quality or biological claim. A coordinate download is not a validation report or experimental-data download.

For a historical question, follow the bounded manual discovery procedure in [references/data-contract.md](references/data-contract.md). This helper only downloads current RCSB entry files; it cannot recreate an archive as of a date.

## Service limits

Requests use fixed HTTPS endpoints, no redirects, a 20-second socket timeout and a 30-second deadline checked between reads. JSON is capped at 2 MiB; mmCIF at 32 MiB. Optional limits may be reduced or raised within hard caps of 60 seconds/socket, 120 seconds/deadline, 8 MiB JSON and 64 MiB mmCIF. A blocked read may continue until its socket timeout. No automatic retry, parallel crawl or archive-wide download is supplied. Respect [RCSB policies](https://www.rcsb.org/pages/policies) and service guidance; cache saved responses and stop on 429 or repeated failures. Existing artifact filenames are not overwritten.

Official documentation: [Search API](https://search.rcsb.org/), [Data API](https://data.rcsb.org/), [file download service](https://www.rcsb.org/docs/programmatic-access/file-download-services), and [extended accession format](https://www.wwpdb.org/documentation/pdb-id-extension-faq).
