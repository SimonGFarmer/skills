# Skills

Self-contained agent skills by Simon G Farmer, with practical tools and focused references for working with real data.

Install NEXRAD:

```sh
npx skills add SimonGFarmer/skills --skill nexrad
```

NEXRAD helps agents find radar stations, discover and download bounded recent or historical Archive II observations, decode measured fields and coordinates, and build analyses or applications. It uses official NOAA/NWS sources and the established Py-ART reader.

Python 3.11 and network access are required. Discovery uses Python's standard library; decoding requires installing [the Py-ART dependencies](skills/nexrad/scripts/requirements.txt) in an isolated environment.

For example, ask your agent: “Use nexrad to find a radar near Oklahoma City, download one observation from May 6, 2024, 00:00–00:10 UTC, and report the available fields and valid reflectivity maximum.” See [the skill instructions](skills/nexrad/SKILL.md) and [the real-data command example](skills/nexrad/references/example.md).

The skill documents reader scope, timestamp meanings, masks and coordinate approximations so derived results retain their scientific context. It is self-contained after installation and has no website dependency.

MIT licensed. NOAA data attribution and upstream dependency licensing are documented within the installed skill.

Install SDSS:

```sh
npx skills add SimonGFarmer/skills --skill sdss
```

SDSS helps agents query official DR20 spectral records by sky region or exact target identifier, compare classifications and redshifts with quality flags, retrieve exact spectra, and work with explicitly labelled legacy photometry. It preserves string identifiers and catalog, archive and delivery provenance. Python 3.11 or later and network access are required; its helpers use only the standard library.

For example, ask your agent: "Use sdss to query a two-arcminute region around RA 229.525575753922, Dec 42.7458537608544. Compare the available spectral records and quality flags, then retrieve one exact DR20 daily spectrum through Valis." See [the skill instructions](skills/sdss/SKILL.md) and [the real-data example](skills/sdss/references/example.md).

The skill distinguishes DR20 spectra from legacy imaging and keeps photometric morphology separate from fitted spectral classes. The SDSS helper code and instructions are MIT licensed; [survey attribution and data terms](skills/sdss/NOTICE.md) remain separate.

Install Argo:

```sh
npx skills add SimonGFarmer/skills --skill argo
```

Argo helps agents discover ocean profiles by region, UTC interval or float identifier, download bounded official GDAC NetCDF files, and decode pressure, temperature and practical salinity with the correct raw or adjusted values, quality flags, errors and provenance. Python 3.11+ and network access are required; decoding needs [the listed dependencies](skills/argo/requirements.txt).

For example, ask your agent: "Use argo to find profiles in the North Atlantic during September 2026, download one and report temperature and salinity against pressure with quality flags." See [the skill instructions](skills/argo/SKILL.md) and [the reproducible example](skills/argo/references/example.md). Core profiles are supported; BGC and trajectory products require their own processing. Helper code and instructions are MIT licensed; [data attribution and upstream terms](skills/argo/references/data-access.md) remain separate.

Install PDB archive data:

```sh
npx skills add SimonGFarmer/skills --skill pdb-archive-data
```

PDB archive data helps agents discover experimental structures and retrieve bounded official RCSB metadata and original mmCIF files with saved provenance. Python 3.10+ and network access are required; retrieval uses the standard library. For example: "Use pdb-archive-data to find experimental crambin entries, retrieve 1CRN, and report its method, resolution and revision with the limitations of the evidence." See [the skill instructions](skills/pdb-archive-data/SKILL.md) and [data contract](skills/pdb-archive-data/references/data-contract.md). Coordinate analysis requires a mature parser and explicit model/conformer selection. Helper code and instructions are MIT licensed; [upstream data terms](skills/pdb-archive-data/NOTICE.md) remain separate.

Install Gaia TAP data:

```sh
npx skills add SimonGFarmer/skills --skill gaia-tap-data
```

Gaia TAP data retrieves bounded Gaia DR3 sky fields from the official ESA service and preserves astrometry, uncertainty, units, selection limits and provenance. Python 3.10+ and direct outbound HTTPS are required; the helper uses only the standard library. For example: "Use gaia-tap-data to retrieve 100 sources near RA 56.75 degrees, Dec 24.12 degrees in a 0.1-degree cone, then report the selection and proper-motion uncertainty without assuming cluster membership or distance." See [the skill instructions](skills/gaia-tap-data/SKILL.md) and [data contract](skills/gaia-tap-data/references/data-contract.md). Helper code and instructions are MIT licensed; [upstream data terms and attribution](skills/gaia-tap-data/NOTICE.md) remain separate.
