"""Offline bounds, scientific semantics, identity and transport tests."""
import importlib.util
import io
import http.client
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse

PATH = Path(__file__).resolve().parents[1] / "skills" / "usgs-earthquakes" / "scripts" / "usgs.py"
SPEC = importlib.util.spec_from_file_location("usgs", PATH)
usgs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usgs)


def event(event_id="ci123", timestamp=1562383193040):
    return {"type": "Feature", "id": event_id,
            "properties": {"time": timestamp, "updated": timestamp + 1000, "mag": -0.2,
                           "magType": "ml", "type": "earthquake", "ids": ",ci123,us-alias,", "status": "reviewed"},
            "geometry": {"type": "Point", "coordinates": [-117.6, 35.7, -0.8]}}


def source(status=200):
    return {"http_status": status, "request_url": "https://earthquake.usgs.gov/test"}


def products():
    raw = event()
    raw["properties"]["products"] = {"origin": [
        {"id": "source:origin:ci123:1", "source": "ci", "code": "123", "status": "UPDATE",
         "preferredWeight": 100, "updateTime": 1000,
         "contents": {"quakeml.xml": {"url": "https://earthquake.usgs.gov/product/origin.xml", "length": 3}}},
        {"id": "source:origin:ci123:2", "source": "us", "code": "456", "status": "UPDATE",
         "preferredWeight": 5, "updateTime": 2000, "contents": {}},
        {"id": "deleted", "status": "DELETE", "preferredWeight": 1000, "updateTime": 3000, "contents": {}},
    ]}
    return raw


class Response(io.BytesIO):
    def __init__(self, body, declared=None, status=200):
        super().__init__(body)
        self.headers = {} if declared is None else {"Content-Length": str(declared)}
        self.status = status


class Tests(unittest.TestCase):
    def args(self, *parts):
        return usgs.parser().parse_args(parts)

    def query(self, *parts):
        return self.args("query", "--start", "2019-07-06T00:00:00Z", "--end", "2019-07-07T00:00:00Z", *parts)

    def test_epoch_milliseconds_and_missing_negative_values(self):
        record = usgs.feature_record(event())
        self.assertEqual(record["origin_time_utc"], "2019-07-06T03:19:53.040Z")
        self.assertEqual(record["depth_km"], -0.8)
        self.assertEqual(record["magnitude"], -0.2)
        raw = event()
        raw["geometry"] = None
        raw["properties"]["mag"] = None
        record = usgs.feature_record(raw)
        self.assertIsNone(record["magnitude"])
        self.assertIsNone(record["depth_km"])
        raw["properties"]["mag"] = 0
        self.assertEqual(usgs.feature_record(raw)["magnitude"], 0)

    def test_invalid_schema_not_empty_science(self):
        for body in (b"bad", b"[]", b'{"type":"wrong"}'):
            with self.assertRaises(usgs.DataError):
                usgs.json_document(body, "FeatureCollection")
        for value in (float("nan"), float("inf"), True, "oops"):
            with self.assertRaises(usgs.DataError):
                usgs.numeric(value)
        raw = event()
        raw["geometry"]["coordinates"][1] = 100
        with self.assertRaises(usgs.DataError):
            usgs.feature_record(raw)

    def test_time_utc_offset_and_bounds(self):
        self.assertEqual(usgs.parse_time("2019-07-05T17:00:00-07:00"), usgs.parse_time("2019-07-06T00:00:00Z"))
        for value in ("2019-07-06", "bad", "2019-07-06T00:00:00"):
            with self.assertRaises(usgs.DataError):
                usgs.parse_time(value)
        for end in ("2019-07-06T00:00:00Z", "2019-07-05T00:00:00Z", "2021-07-07T00:00:00Z"):
            args = self.query()
            args.end = end
            with self.assertRaises(usgs.DataError):
                usgs.query_parameters(args)

    def test_bounding_box_date_line_and_circle(self):
        params = usgs.query_parameters(self.query("--bbox", "170", "-20", "190", "20"))
        self.assertEqual(params["maxlongitude"], 190)
        circle = self.query("--latitude", "35.7", "--longitude", "-117.6", "--radius-km", "100")
        self.assertEqual(usgs.query_parameters(circle)["maxradiuskm"], 100)
        for parts in (("--bbox", "170", "-20", "-170", "20"), ("--latitude", "35"),
                      ("--latitude", "91", "--longitude", "0", "--radius-km", "10"),
                      ("--bbox", "0", "0", "1", "1", "--latitude", "0", "--longitude", "0", "--radius-km", "1"),
                      ("--limit", "1001"), ("--offset", "0"), ("--min-magnitude", "nan")):
            with self.assertRaises(usgs.DataError):
                usgs.query_parameters(self.query(*parts))
        self.assertNotIn("eventtype", usgs.query_parameters(self.query("--event-type", "all")))
        self.assertEqual(usgs.query_parameters(self.query())["eventtype"], "earthquake")

    def test_url_host_redirect_and_identifier(self):
        usgs.official_url("https://earthquake.usgs.gov/product/origin.xml")
        for url in ("http://earthquake.usgs.gov/a", "https://evil.test/a", "https://earthquake.usgs.gov.evil.test/a",
                    "https://user@earthquake.usgs.gov/a", "https://earthquake.usgs.gov:444/a"):
            with self.assertRaises(usgs.DataError):
                usgs.official_url(url)
        for value in (123, "", "../other", "ci1&format=xml"):
            with self.assertRaises(usgs.DataError):
                usgs.identifier(value)
        with self.assertRaises(usgs.DataError):
            usgs.NoRedirect().redirect_request(None, None, 302, None, {}, "https://evil.test")

    def test_stream_caps_truncation_and_deadline(self):
        self.assertEqual(usgs.bounded_read(Response(b"abc", 3), 3, time.monotonic() + 10), b"abc")
        for response in (Response(b"abcd"), Response(b"a", 4), Response(b"a", 3), Response(b"a", "bad"), Response(b"a", -1)):
            with self.assertRaises(usgs.DataError):
                usgs.bounded_read(response, 3, time.monotonic() + 10)
        with self.assertRaises(usgs.DataError):
            usgs.bounded_read(Response(b"a"), 3, time.monotonic() - 1)

    def test_transport_success_manifest_and_204(self):
        for status, body in ((200, b"abc"), (204, b"")):
            opener = unittest.mock.Mock()
            opener.open.return_value = Response(body, len(body), status)
            with patch.object(usgs.urllib.request, "build_opener", return_value=opener):
                actual, manifest = usgs.request("https://earthquake.usgs.gov/test")
            self.assertEqual(actual, body)
            self.assertEqual(manifest["sha256"], usgs.hashlib.sha256(body).hexdigest())
            self.assertEqual(manifest["http_status"], status)

    def test_network_and_http_errors(self):
        for error in (urllib.error.URLError("TLS fail"), TimeoutError("timeout"), http.client.IncompleteRead(b"partial", 20),
                      *[urllib.error.HTTPError("https://earthquake.usgs.gov", code, "failure", {}, None)
                        for code in (400, 404, 409, 429, 503)]):
            opener = unittest.mock.Mock()
            opener.open.side_effect = error
            with patch.object(usgs.urllib.request, "build_opener", return_value=opener), self.assertRaises(usgs.DataError):
                usgs.request("https://earthquake.usgs.gov/test")

    def test_catalog_count_and_one_based_pages(self):
        raw = {"type": "FeatureCollection", "features": [event("ci1"), event("ci2")]}
        args = self.query("--limit", "2")
        with patch.object(usgs, "request", side_effect=[(b"5", source()), (json.dumps(raw).encode(), source())]) as mocked:
            result = usgs.catalog_query(args)
        self.assertEqual(result["returned"], 2)
        self.assertEqual(result["next_offset"], 3)
        self.assertTrue(result["has_more_at_preflight"])
        self.assertFalse(result["snapshot_atomic"])
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(mocked.call_args_list[1].args[0]).query)
        self.assertEqual(query["offset"], ["1"])
        self.assertEqual(query["orderby"], ["time-asc"])
        self.assertNotIn("limit", mocked.call_args_list[0].args[0])

    def test_large_count_fails_before_data_download(self):
        with patch.object(usgs, "request", return_value=(b"20001", source())) as mocked, self.assertRaises(usgs.DataError):
            usgs.catalog_query(self.query())
        self.assertEqual(mocked.call_count, 1)

    def test_catalog_empty_retains_count_drift(self):
        with patch.object(usgs, "request", side_effect=[(b"4", source()), (b"", source(204))]):
            result = usgs.catalog_query(self.query())
        self.assertEqual(result["count_at_preflight"], 4)
        self.assertEqual(result["events"], [])
        self.assertIsNone(result["next_offset"])

    def test_duplicate_page_fails(self):
        raw = {"type": "FeatureCollection", "features": [event(), event()]}
        with patch.object(usgs, "request", side_effect=[(b"2", source()), (json.dumps(raw).encode(), source())]), self.assertRaises(usgs.DataError):
            usgs.catalog_query(self.query())

    def test_csv_uncertainty_nulls_units_and_strings(self):
        body = ("id,time,updated,latitude,longitude,depth,mag,magType,horizontalError,depthError,magError,magNst\n"
                "ci123,2019-07-06T03:19:53.040Z,2019-07-06T03:20:00Z,35.7,-117.6,-0.8,0,ml,0,,0.02,6\n").encode()
        text, rows = usgs.csv_records(body)
        self.assertIn("horizontalError", text)
        self.assertEqual(rows[0]["id"], "ci123")
        self.assertEqual(rows[0]["depth_km"], -0.8)
        self.assertEqual(rows[0]["horizontal_error_km"], 0)
        self.assertIsNone(rows[0]["depth_error_km"])
        self.assertEqual(rows[0]["magnitude_error"], 0.02)
        self.assertEqual(rows[0]["magnitude"], 0)
        with self.assertRaises(usgs.DataError):
            usgs.csv_records(b"oops\n123\n")

    def test_product_preference_weight_then_update_excludes_delete(self):
        inventory = usgs.product_inventory(products())
        self.assertEqual([p["id"] for p in inventory if p["preferred_in_response"]], ["source:origin:ci123:1"])
        raw = products()
        raw["properties"]["products"]["origin"][1]["preferredWeight"] = 100
        inventory = usgs.product_inventory(raw)
        self.assertEqual([p["id"] for p in inventory if p["preferred_in_response"]], ["source:origin:ci123:2"])

    def test_product_without_files_empty_array(self):
        raw = products()
        raw["properties"]["products"]["general-link"] = [{"id": "link", "status": "UPDATE", "contents": []}]
        inventory = usgs.product_inventory(raw)
        self.assertEqual(next(p["contents"] for p in inventory if p["type"] == "general-link"), {})
        raw["properties"]["products"]["general-link"][0]["contents"] = ["invalid"]
        with self.assertRaises(usgs.DataError):
            usgs.product_inventory(raw)

    def test_detail_alias_and_mismatch(self):
        args = self.args("detail", "--event-id", "us-alias")
        with patch.object(usgs, "request", return_value=(json.dumps(products()).encode(), source())):
            result = usgs.detail(args)
        self.assertEqual(result["events"][0]["id"], "ci123")
        self.assertEqual(result["requested_id"], "us-alias")
        args.event_id = "wrong"
        with patch.object(usgs, "request", return_value=(json.dumps(products()).encode(), source())), self.assertRaises(usgs.DataError):
            usgs.detail(args)
        with patch.object(usgs, "request", return_value=(b"", source(204))), self.assertRaises(usgs.DataError):
            usgs.detail(args)
        malformed = products()
        malformed["properties"]["ids"] = ["ci123"]
        with patch.object(usgs, "request", return_value=(json.dumps(malformed).encode(), source())), self.assertRaises(usgs.DataError):
            usgs.detail(args)

    def download_args(self, output):
        return self.args("product", "--event-id", "ci123", "--product-type", "origin", "--product-id", "source:origin:ci123:1",
                         "--content", "quakeml.xml", "--output", str(output))

    def product_result(self):
        return {"products": usgs.product_inventory(products()), "source": source(), "events": [{"id": "ci123"}]}

    def test_download_preserves_bytes_manifest_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "origin.xml"
            args = self.download_args(output)
            with patch.object(usgs, "detail", return_value=self.product_result()), patch.object(usgs, "request", return_value=(b"abc", source())):
                result = usgs.download_product(args)
                self.assertEqual(output.read_bytes(), b"abc")
                self.assertEqual(result["product"]["code"], "123")
                with self.assertRaises(usgs.DataError):
                    usgs.download_product(args)
            self.assertEqual(output.read_bytes(), b"abc")
            self.assertEqual(list(Path(directory).iterdir()), [output])

    def test_download_caps_changed_version_missing_content_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "origin.xml"
            for case in ("changed", "content", "cap", "truncated", "empty"):
                args = self.download_args(output)
                if case == "changed":
                    args.product_id = "different"
                if case == "content":
                    args.content = "not-present"
                if case == "cap":
                    args.max_bytes = 2
                body = b"x" if case == "truncated" else b"" if case == "empty" else b"abc"
                with patch.object(usgs, "detail", return_value=self.product_result()), patch.object(usgs, "request", return_value=(body, source())), self.assertRaises(usgs.DataError):
                    usgs.download_product(args)
                self.assertFalse(output.exists())

    def test_cli_error_stderr_and_no_result(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(usgs.sys, "stdout", stdout), patch.object(usgs.sys, "stderr", stderr):
            code = usgs.main(["detail", "--event-id", "bad&id"])
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("error", json.loads(stderr.getvalue()))

    def test_json_output_portable_default_windows_encoding(self):
        stdout = io.StringIO()
        document = {"place": "Türkiye — earthquake"}
        with patch.object(usgs.sys, "stdout", stdout), patch.object(usgs, "feed", return_value=document):
            code = usgs.main(["feed"])
        self.assertEqual(code, 0)
        encoded = stdout.getvalue().encode("cp1252")
        self.assertEqual(json.loads(encoded.decode("utf-8")), document)


if __name__ == "__main__":
    unittest.main()
