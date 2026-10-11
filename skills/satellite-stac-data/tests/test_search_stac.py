"""Offline behavioral tests; fixtures are synthetic, not satellite observations."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.parse
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("search_stac", ROOT / "scripts" / "search_stac.py")
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


class Response(io.BytesIO):
    def __init__(self, payload, declared=None):
        super().__init__(payload)
        self.headers = {} if declared is None else {"Content-Length": str(declared)}


class FakeOpener:
    def __init__(self, payload, declared=None):
        self.payload, self.declared = payload, declared
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return Response(self.payload, self.declared)


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.page = json.loads((ROOT / "tests" / "fixtures" / "page.json").read_text(encoding="utf-8"))
        self.query = helper.make_query("landsat-c2-l2", [12.4, 41.8, 12.6, 42], "2024-06-01", "2024-08-31")

    def test_fixed_post_one_page_and_saved_bounds(self):
        opener = FakeOpener(json.dumps(self.page).encode())
        result = helper.fetch_page(self.query, "synthetic-cursor", opener=opener)
        self.assertEqual(result, self.page)
        self.assertEqual(len(opener.requests), 1)
        request, timeout = opener.requests[0]
        self.assertEqual(request.full_url, helper.SEARCH)
        self.assertEqual(request.get_method(), "POST")
        body = json.loads(request.data)
        self.assertEqual(body["bbox"], self.query["bbox"])
        self.assertEqual(body["datetime"], self.query["datetime"])
        self.assertEqual(body["token"], "synthetic-cursor")
        self.assertEqual(timeout, 30)

    def test_unknown_cloud_and_original_provenance_preserved(self):
        result = helper.package_page(self.page, self.query)
        self.assertIsNone(result["summary"][0]["cloud_cover"])
        self.assertEqual(result["stac"], self.page)
        item = copy.deepcopy(self.page["features"][0])
        for value in [None, True, "4.2", -1, 101, float("nan")]:
            item["properties"]["eo:cloud_cover"] = value
            self.assertIsNone(helper.summarize(item, self.query["bbox"])["cloud_cover"])
        item["properties"].pop("eo:cloud_cover")
        self.assertIsNone(helper.summarize(item, self.query["bbox"])["cloud_cover"])
        item["properties"]["eo:cloud_cover"] = 4.2
        self.assertEqual(helper.summarize(item, self.query["bbox"])["cloud_cover"], 4.2)

    def test_explicit_continuation_and_page_budget(self):
        first = helper.package_page(self.page, self.query, 1, 2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "page.json"
            path.write_text(json.dumps(first), encoding="utf-8")
            query, token, count, budget = helper.load_continuation(path)
        self.assertEqual(query, self.query)
        self.assertEqual((token, count, budget), ("synthetic-pagination-cursor", 2, 2))
        last = helper.package_page(self.page, query, count, budget)
        self.assertTrue(last["has_more"])
        self.assertTrue(last["page_budget_exhausted"])
        self.assertIsNone(last["continuation"])

    def test_empty_page_is_valid(self):
        empty = {"type": "FeatureCollection", "features": [], "links": []}
        result = helper.fetch_page(self.query, opener=FakeOpener(json.dumps(empty).encode()))
        output = helper.package_page(result, self.query)
        self.assertEqual(output["summary"], [])
        self.assertFalse(output["has_more"])
        self.assertIsNone(output["continuation"])

    def test_get_next_link_is_rebuilt_from_original_query(self):
        link = {"rel": "next", "href": helper.SEARCH + "?token=synthetic-next&limit=1000"}
        self.assertEqual(helper.next_token([link]), "synthetic-next")
        opener = FakeOpener(json.dumps(self.page).encode())
        helper.fetch_page(self.query, helper.next_token([link]), opener=opener)
        self.assertEqual(json.loads(opener.requests[0][0].data)["limit"], 20)

    def test_external_next_and_redirects_rejected(self):
        for href in ["https://example.invalid/search?token=x", helper.SEARCH + "/other?token=x", "http://planetarycomputer.microsoft.com/api/stac/v1/search?token=x"]:
            with self.assertRaises(ValueError):
                helper.next_token([{"rel": "next", "href": href}])
        with self.assertRaises(ValueError):
            helper.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://example.invalid/")

    def test_transfer_limit_declared_and_streamed(self):
        for declared in [None, 2048]:
            with self.assertRaisesRegex(ValueError, "byte limit"):
                helper.fetch_page(self.query, max_bytes=1024, opener=FakeOpener(b"x" * 2048, declared))

    def test_server_page_size_and_shape_checked(self):
        bad = copy.deepcopy(self.page)
        bad["features"] *= 21
        with self.assertRaises(ValueError):
            helper.fetch_page(self.query, opener=FakeOpener(json.dumps(bad).encode()))
        bad = copy.deepcopy(self.page)
        bad["features"][0]["collection"] = "sentinel-2-l2a"
        with self.assertRaises(ValueError):
            helper.fetch_page(self.query, opener=FakeOpener(json.dumps(bad).encode()))

    def test_malformed_optional_metadata_fails_cleanly(self):
        for key, value in [("assets", None), ("assets", {"tilejson": None}), ("links", None)]:
            bad = copy.deepcopy(self.page)
            bad["features"][0][key] = value
            with self.assertRaisesRegex(ValueError, "metadata"):
                helper.fetch_page(self.query, opener=FakeOpener(json.dumps(bad).encode()))
        bad_next = copy.deepcopy(self.page["links"])
        bad_next[0]["method"] = None
        with self.assertRaisesRegex(ValueError, "method"):
            helper.next_token(bad_next)

    def test_acquisition_identity_and_datetime_checked(self):
        for value in ["", "   ", None]:
            bad = copy.deepcopy(self.page)
            bad["features"][0]["id"] = value
            with self.assertRaisesRegex(ValueError, "STAC item"):
                helper.fetch_page(self.query, opener=FakeOpener(json.dumps(bad).encode()))
        for value in [None, "not-a-date", "2024-06-01", "2024-06-01T12:00:00", "2024-06-01T12:00:00+02:00", "2024-02-30T12:00:00Z"]:
            bad = copy.deepcopy(self.page)
            bad["features"][0]["properties"]["datetime"] = value
            with self.assertRaisesRegex(ValueError, "UTC acquisition datetime"):
                helper.fetch_page(self.query, opener=FakeOpener(json.dumps(bad).encode()))

    def test_expired_response_deadline_rejected(self):
        opener = FakeOpener(json.dumps(self.page).encode())
        with patch.object(helper.time, "monotonic", side_effect=[0, 31]):
            with self.assertRaises(TimeoutError):
                helper.fetch_page(self.query, opener=opener)

    def test_invalid_bounds_dates_and_limits(self):
        for box in [[179, 0, -179, 1], [12, 76, 13, 77], [12, 40, 15, 41], [12, 40, float("nan"), 41]]:
            with self.assertRaises(ValueError):
                helper.make_query("landsat-c2-l2", box, "2024-06-01", "2024-08-31")
        for start, end in [("2024-02-30", "2024-03-01"), ("2025-01-01", "2024-01-01"), ("2023-01-01", "2025-01-01")]:
            with self.assertRaises(ValueError):
                helper.make_query("landsat-c2-l2", [12, 40, 13, 41], start, end)
        with self.assertRaises(ValueError):
            helper.make_query("landsat-c2-l2", [12, 40, 13, 41], "2024-01-01", "2024-02-01", limit=41)

    def test_sas_removed_without_losing_unsigned_metadata(self):
        original = {"href": "https://example.blob.core.windows.net/container/a.tif?sig=SYNTHETIC_NOT_A_CREDENTIAL&se=SYNTHETIC_EXPIRY&foo=keep", "title": "Raster band"}
        clean = helper.redact_sas(original)
        self.assertNotIn("sig=", clean["href"])
        self.assertNotIn("se=", clean["href"])
        self.assertIn("foo=keep", clean["href"])
        self.assertEqual(clean["title"], original["title"])
        self.assertIn("sig=", original["href"])

    def test_preview_preserves_rgb_order_and_shared_grid(self):
        url = helper.bbox_preview(self.page["features"][0], self.query["bbox"])
        parsed = urllib.parse.urlsplit(url)
        params = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(params["assets"], ["red", "green", "blue"])
        self.assertEqual(params["rescale"], ["7000,30000"])
        self.assertEqual(params["dst_crs"], ["EPSG:4326"])
        self.assertEqual(params["resampling"], ["nearest"])
        self.assertEqual(params["return_mask"], ["true"])
        self.assertTrue(parsed.path.endswith("/512x512.png"))
        item = copy.deepcopy(self.page["features"][0])
        item["assets"]["tilejson"]["href"] = "https://example.invalid/tilejson.json"
        self.assertIsNone(helper.bbox_preview(item, self.query["bbox"]))

    def test_cli_existing_output_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing.json"
            output.write_text("existing user result", encoding="utf-8")
            with patch.object(helper, "fetch_page", return_value=self.page), patch("sys.stderr", new=io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    helper.main(["--collection", "landsat-c2-l2", "--bbox", "12.4", "41.8", "12.6", "42.0", "--start", "2024-06-01", "--end", "2024-08-31", "--output", str(output)])
            self.assertEqual(error.exception.code, 1)
            self.assertEqual(output.read_text(encoding="utf-8"), "existing user result")

    def test_cli_continuation_cannot_expand_search(self):
        with patch.object(helper, "fetch_page") as fetch, patch("sys.stderr", new=io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                helper.main(["--continue-from", "unused.json", "--limit", "40"])
        self.assertEqual(error.exception.code, 1)
        fetch.assert_not_called()

    def test_cli_429_reports_retry_after_without_retry(self):
        failure = urllib.error.HTTPError(helper.SEARCH, 429, "Too Many Requests", {"Retry-After": "120"}, None)
        stderr = io.StringIO()
        with patch.object(helper, "fetch_page", side_effect=failure) as fetch, patch("sys.stderr", new=stderr):
            with self.assertRaises(SystemExit) as error:
                helper.main(["--collection", "landsat-c2-l2", "--bbox", "12.4", "41.8", "12.6", "42.0", "--start", "2024-06-01", "--end", "2024-08-31"])
        self.assertEqual(error.exception.code, 1)
        self.assertEqual(fetch.call_count, 1)
        self.assertIn("HTTP 429", stderr.getvalue())
        self.assertIn("Retry-After: 120", stderr.getvalue())
        self.assertIn("No automatic retry", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
