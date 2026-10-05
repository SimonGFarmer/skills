# Query photometry and spectral records

Run these from the installed skill folder with Python 3.11 or later, writing outputs to an unrelated working directory. Replace the helper path with its absolute installed path if running elsewhere. The core workflow needs no pip packages. On Windows use `py -3.11` if `python` is unavailable.

```sh
python scripts/sdss.py cone --ra 229.525575753922 --dec 42.7458537608544 --radius 2 --limit 10 > region.json
python scripts/sdss.py photo-id --id 1237662301903192106 > photometry.json
python scripts/sdss.py target --id-type specobjid --id 1889376924388583424 > legacy.json
python scripts/sdss.py spectrum --id sdss3-apo-sdss-26-1678-53433-0425 --output legacy.fits > legacy-download.json
python scripts/sdss.py spectrum --id sdss5-apo-boss-daily-v6_2_1-101317-60108-27021600639497457-125068678 --delivery valis --output boss-daily.fits > boss-download.json
```

This example compares legacy and DR20 spectral products. Photometric object `1237662301903192106` links to legacy specobjid `1889376924388583424`, with pipeline GALAXY/STARBURST, z about 0.04027193 and zwarning 16. A nearby DR20 BOSS daily record has specobjid `12506867801013176010800060201`, z about 0.04029697 and zwarning 0. These are pipeline measurements, not a certified classification or a claim that the photometric legacy association changed. Verify the returned values and provenance because services and catalog contents can change. The legacy example uses direct SAS delivery; the daily example uses Valis. Both services can return transport errors, which must remain distinct from unavailable spectra.

For pagination, use `--limit 2` for the cone, then copy the returned `next_after` string into `--after` on the identical cone command. Never interpret the first ID-ordered record as the nearest. For a narrow comparison query try RA 0, Dec -89 with radius 0.01 arcminutes; report the actual result rather than assuming emptiness.

For a photometric target without a linked spectrum, retain its magnitudes/morphology and report the missing legacy association. Do not guess a spectrum filename or borrow a neighboring spectrum. If a target ID yields multiple observations, select an exact ALLSPEC ID according to the requested instrument, product or epoch and state the choice.

The downloaded files can be opened in Astropy or another maintained reader. Inspect HDU names, units and masks before analysis; the download manifest supplies the immutable file hash and survey provenance. Follow [interpretation.md](interpretation.md) and the file's official data model.
