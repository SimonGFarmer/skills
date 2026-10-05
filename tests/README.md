# Helper tests

Create a Python 3.11 virtual environment and install `skills/nexrad/scripts/requirements.txt`, then run:

```sh
python -m unittest discover -s tests -v
```

Offline tests cover archive pagination and UTC bounds, metadata exclusion, download caps and failures, preservation of existing files, and masked field summaries. They do not require NOAA network access.

For an integration check, install the collection from a local path into an isolated project, follow the installed skill's historical example, and discover a recent UTC window. Decode one bounded download from each window. Check field units, masks, ray time origins and coordinate dimensions; real-data availability depends on upstream services. Keep downloads and generated outputs outside this repository.
