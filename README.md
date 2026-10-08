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
