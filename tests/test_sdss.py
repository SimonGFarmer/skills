"""Offline transport, identity and bounds checks; no survey snapshots bundled."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "skills" / "sdss" / "scripts" / "sdss.py"
spec = importlib.util.spec_from_file_location("sdss", PATH)
sdss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdss)


class Response(io.BytesIO):
    def __init__(self, body, declared=None):
        super().__init__(body)
        self.headers = {} if declared is None else {"Content-Length": str(declared)}


class Tests(unittest.TestCase):
    def args(self, *parts):
        return sdss.parser().parse_args(parts)

    def test_cone_bounds_wrap_poles(self):
        self.assertEqual(sdss.cone(359.999, 90, 60), "359.999,90,60")
        for values in ((360, 0, 1), (-1, 0, 1), (0, 91, 1), (0, 0, 0), (0, 0, 61), (float("nan"), 0, 1)):
            with self.assertRaises(sdss.DataError):
                sdss.cone(*values)

    def test_identifier_precision_and_injection(self):
        value = "12506867801013176010800060201"
        self.assertEqual(sdss.identifier(value, True), value)
        for value in (123, "1' OR 1=1", "", "123;drop table allspec"):
            with self.assertRaises(sdss.DataError):
                sdss.identifier(value)

    def test_rows_json_contract(self):
        for body in (b"not json", b"{}", b"[]", b'[{"Rows":[{"error_message":"SQL failure"}]}]', b'[{"Rows":[{"specobjid":9007199254740993}]}]'):
            with patch.object(sdss, "request", return_value=body), self.assertRaises(sdss.DataError):
                sdss.sql_rows("select 1", "dr20", 30)
        payload = [{"Rows": [{"specobjid": "12506867801013176010800060201", "class": None}]}]
        with patch.object(sdss, "request", return_value=json.dumps(payload).encode()):
            rows, _ = sdss.sql_rows("select 1", "dr20", 30)
            self.assertEqual(rows[0]["specobjid"], payload[0]["Rows"][0]["specobjid"])

    def test_stream_declared_bounds_and_deadline(self):
        self.assertEqual(sdss.bounded_read(Response(b"abc"), 3), b"abc")
        for response in (Response(b"abcd"), Response(b"a", 4)):
            with self.assertRaises(sdss.DataError):
                sdss.bounded_read(response, 3)
        with self.assertRaises(sdss.DataError):
            sdss.bounded_read(Response(b"a", 3), 3)
        with self.assertRaises(sdss.DataError):
            sdss.bounded_read(Response(b"x"), 3, time.monotonic() - 1)

    def test_paging_and_empty(self):
        args = self.args("cone", "--ra", "1", "--dec", "2", "--radius", "0.01", "--limit", "2")
        with patch.object(sdss, "sql_rows", return_value=([{"allspec_id": x} for x in ("a", "b", "c")], "url")):
            result = sdss.query(args)
        self.assertEqual([r["allspec_id"] for r in result["rows"]], ["a", "b"])
        self.assertEqual(result["next_after"], "b")
        args.after = result["next_after"]
        with patch.object(sdss, "sql_rows", return_value=([{"allspec_id": "c"}], "url")) as mock:
            result = sdss.query(args)
            self.assertIn("a.allspec_id>'b'", mock.call_args.args[0])
        self.assertFalse(result["has_more"])
        with patch.object(sdss, "sql_rows", return_value=([], "url")):
            self.assertEqual(sdss.query(args)["status"], "empty")

    def test_missing_ambiguous_identity(self):
        args = self.args("target", "--id", "record")
        for rows in ([{}], [{"allspec_id": "a"}, {"allspec_id": "a"}]):
            with patch.object(sdss, "sql_rows", return_value=(rows, "url")), self.assertRaises(sdss.DataError):
                sdss.query(args)

    def test_missing_measurements_flags_and_provenance(self):
        self.assertFalse(sdss.enrich({})["pipeline_redshift_unflagged"])
        self.assertIsNone(sdss.enrich({"sdss_phase": None})["parameter_source"])
        legacy = sdss.enrich({"instrument": "sdss", "sdss_phase": 3, "z": 0.04, "zwarning": 16,
                              "sas_url": "https://data.sdss.org/sas/dr17/spectrum.fits"})
        self.assertEqual(legacy["catalog_release"], "DR20")
        self.assertEqual(legacy["archive_release"], "DR17")
        self.assertFalse(legacy["pipeline_redshift_unflagged"])
        self.assertFalse(sdss.enrich({"z": -999, "zwarning": 0})["pipeline_redshift_unflagged"])
        photo = sdss.enrich({"type": 6, "specobjid": "0", "psfMag_r": None}, True)
        self.assertEqual(photo["morphology"], "point-like")
        self.assertEqual(photo["spectrum_association"], "none")
        self.assertIsNone(photo["psfMag_r"])
        self.assertNotIn("class", photo)
        for value in (None, '', ' ', '0', '-999', 'invalid'):
            self.assertEqual(sdss.enrich({'specobjid': value}, True)['spectrum_association'], 'none')
        with self.assertRaises(sdss.DataError):
            sdss.enrich({'sas_url': 123})

    def test_url_scope_and_redirect(self):
        sdss.archive_url("https://data.sdss.org/sas/dr20/test/spec.fits")
        for value in ("http://data.sdss.org/sas/dr20/a.fits", "https://evil.example/sas/dr20/a.fits", "https://data.sdss.org/sas/dr20/../a.fits", "https://data.sdss.org/sas/dr20/a.fits?token=secret"):
            with self.assertRaises(sdss.DataError):
                sdss.archive_url(value)
        with self.assertRaises(sdss.DataError):
            sdss.NoRedirect().redirect_request(None, None, 302, None, None, "https://elsewhere.example")

    def test_timeout_is_failure_not_empty(self):
        args = self.args("target", "--id", "record")
        with patch.object(sdss, "request", side_effect=TimeoutError("timed out")), self.assertRaises(TimeoutError):
            sdss.query(args)

    def test_download_identity_no_spectrum_and_atomic_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "one.fits"
            args = self.args("spectrum", "--id", "record", "--output", str(destination))
            result = {"rows": [{"allspec_id": "record", "sas_url": None}], "has_more": False, "query_url": "url", "retrieved_at": "date"}
            with patch.object(sdss, "query", return_value=result):
                self.assertEqual(sdss.download(args)["status"], "no_spectrum")
            result["rows"][0]["sas_url"] = "https://data.sdss.org/sas/dr20/test/spec.fits"
            body = b"SIMPLE  =" + b" " * (2880 - 9)
            with patch.object(sdss, "query", return_value=result), patch.object(sdss, "request", return_value=body):
                result = sdss.download(args)
                self.assertEqual(destination.read_bytes(), body)
                self.assertEqual(result["bytes"], len(body))
                with self.assertRaises(sdss.DataError):
                    sdss.download(args)
            self.assertEqual(list(Path(tmp).iterdir()), [destination])

    def test_truncated_fits_not_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / 'truncated.fits'
            args = self.args('spectrum', '--id', 'record', '--output', str(destination))
            result = {'rows': [{'allspec_id': 'record', 'sas_url': 'https://data.sdss.org/sas/dr20/test/spec.fits'}],
                      'has_more': False, 'query_url': 'url', 'retrieved_at': 'date'}
            with patch.object(sdss, 'query', return_value=result), patch.object(sdss, 'request', return_value=b'SIMPLE  ='), self.assertRaises(sdss.DataError):
                sdss.download(args)
            self.assertFalse(destination.exists())

    def valis_record(self):
        return {'instrument': 'boss', 'coadd': 'daily', 'run2d': 'v6_2_1', 'sdss_phase': 5, 'plate': 101317, 'mjd': 60108,
                'sas_url': 'https://data.sdss.org/sas/dr20/spectro/boss/redux/v6_2_1/spectra/daily/lite/101XXX/101317/60108/spec-101317-60108-27021600639497457.fits'}

    def test_valis_exact_product_resolution(self):
        row = self.valis_record()
        payload = json.dumps({'exists': True, 'url': row['sas_url']}).encode()
        with patch.object(sdss, 'request', return_value=payload) as mock:
            url, resolution = sdss.valis_delivery(row, row['sas_url'], 30)
            self.assertTrue(url.startswith('https://api.sdss.org/valis/file/specLite/download?'))
            self.assertIn('kwargs=catalogid%3D27021600639497457', url)
            self.assertIn('release=DR20', url)
            self.assertEqual(mock.call_args.args, (resolution, sdss.MAX_JSON, 30))

    def test_valis_rejects_mismatched_or_missing_product(self):
        row = self.valis_record()
        for payload in (b'not json', b'{}', b'[]', json.dumps({'exists': False, 'url': row['sas_url']}).encode(),
                        json.dumps({'exists': True, 'url': row['sas_url'].replace('60108', '60109')}).encode()):
            with patch.object(sdss, 'request', return_value=payload), self.assertRaises(sdss.DataError):
                sdss.valis_delivery(row, row['sas_url'], 30)
        for update in ({'coadd': 'epoch'}, {'plate': 1}, {'mjd': 1}, {'instrument': 'manga'}, {'sdss_phase': 4}):
            with patch.object(sdss, 'request') as mock, self.assertRaises(sdss.DataError):
                sdss.valis_delivery({**row, **update}, row['sas_url'], 30)
            mock.assert_not_called()

    def test_valis_manifest_preserves_sas_provenance(self):
        row = {'allspec_id': 'record', **self.valis_record()}
        result = {'rows': [row], 'has_more': False, 'query_url': 'url', 'retrieved_at': 'date'}
        body = b'SIMPLE  =' + b' ' * (2880 - 9)
        with tempfile.TemporaryDirectory() as tmp:
            args = self.args('spectrum', '--id', 'record', '--output', str(Path(tmp) / 'one.fits'), '--delivery', 'valis')
            with patch.object(sdss, 'query', return_value=result), patch.object(sdss, 'request', side_effect=[json.dumps({'exists': True, 'url': row['sas_url']}).encode(), body]):
                manifest = sdss.download(args)
            self.assertEqual(manifest['archive_url'], row['sas_url'])
            self.assertEqual(manifest['delivery'], 'valis')
            self.assertIn('/file/specLite/download?', manifest['delivery_url'])
            self.assertEqual(manifest['record']['allspec_id'], 'record')


if __name__ == "__main__":
    unittest.main()
