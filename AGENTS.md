# Maintaining the collection

Keep each skill self-contained under `skills/NAME`, with matching valid frontmatter. Put runtime helpers and references inside that folder; verify from an installed copy in an unrelated directory. Keep root documentation concise and document prerequisites inside each installed skill.

Verify official/upstream source contracts before changing parser claims. Test bounded archive discovery/download and real decoding, plus offline edge cases. Preserve units, masks, coordinates, timestamps and provenance; distinguish data restrictions from display choices. Keep dependencies explicit and attribution intact.

Run the offline tests in `tests/` for helper changes. Validate skill metadata with the official Agent Skills `skills-ref` validator. Keep real-data downloads and generated outputs outside the repository; document reproducible commands rather than committing operational logs.
