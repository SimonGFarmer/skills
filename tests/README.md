# Helper tests

Create and activate a Python 3.11 virtual environment, then run the offline suite. NumPy is needed for the NEXRAD masked-array tests; Py-ART is only needed for live decoding.

```sh
python -m pip install numpy==1.26.4
python -m unittest discover -s tests -v
```

Offline tests cover archive pagination and UTC bounds, metadata exclusion, download caps and failures, preservation of existing files, and masked field summaries. They do not require NOAA network access.

For a NEXRAD integration check, also install `skills/nexrad/scripts/requirements.txt`, then install the collection from a local path into an isolated project, follow the installed skill's historical example, and discover a recent UTC window. Decode one bounded download from each window. Check field units, masks, ray time origins and coordinate dimensions; real-data availability depends on upstream services. Keep downloads and generated outputs outside this repository.

SDSS tests use only Python's standard library and can run separately with:

```sh
python -m unittest discover -s tests -p test_sdss.py -v
```

They cover catalog identity and pagination, missing measurements, transport bounds, exact Valis product resolution and download provenance. For a bounded live check, follow the installed SDSS example and inspect the downloaded FITS with a maintained reader; decoding is separate from the helper's original-file download. Keep FITS and manifests outside the repository.

## Collection checks

Install the official reference validator pinned by CI, then validate installed
skill metadata, the README install commands, and relative links:

```sh
python -m pip install "skills-ref @ git+https://github.com/agentskills/agentskills.git@83021e2be457a9b6679148719c1f6074f0ad975e#subdirectory=skills-ref"
python tests/validate_collection.py
```
