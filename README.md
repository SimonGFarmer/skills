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
