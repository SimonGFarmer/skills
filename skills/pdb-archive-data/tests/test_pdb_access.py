"""Offline transport/contract fixtures are synthetic, never scientific evidence."""
import hashlib
import http.client
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pdb_access.py"
SPEC = importlib.util.spec_from_file_location("pdb_access", SCRIPT)
pdb = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pdb
SPEC.loader.exec_module(pdb)

ENTRY_FIXTURE = {
    "rcsb_id": "1CRN",
    "struct": {"title": "Synthetic transport fixture, not scientific data"},
    "exptl": None,
    "rcsb_entry_info": {"structure_determination_methodology": "experimental",
                        "resolution_combined": None},
    "rcsb_accession_info": {"initial_release_date": None, "revision_date": None},
    "unknown_future_field": {"preserve": "unchanged"},
}
CIF_FIXTURE = b"# synthetic syntax fixture, not molecular data\ndata_transport_fixture\n_entry.id 1CRN\n"


class Response(io.BytesIO):
    def __init__(self, raw=b"{}", status=200, headers=None, url=pdb.SEARCH_URL):
        super().__init__(raw)
        self.status, self.headers, self.url = status, headers or {}, url
        self.read_calls = 0

    def geturl(self):
        return self.url

    def read(self, size=-1):
        self.read_calls += 1
        return super().read(size)


class Opener:
    def __init__(self, response):
        self.response, self.calls = response, []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def fixture_fetch(raw_metadata=None, raw_cif=CIF_FIXTURE):
    calls = []
    def fetcher(url, limits, cap, payload=None):
        calls.append((url, cap, payload))
        raw = raw_cif if url.startswith(pdb.CIF_BASE) else json.dumps(
            ENTRY_FIXTURE if raw_metadata is None else raw_metadata).encode()
        return raw, {"url": url, "http_status": 200, "sha256": hashlib.sha256(raw).hexdigest(),
                     "bytes": len(raw), "retrieved_at_utc": "fixture timestamp"}
    return fetcher, calls


class AccessionAndQueryTests(unittest.TestCase):
    def test_classic_extended_and_identity_normalization(self):
        self.assertEqual(pdb.accession("1crn"), "1CRN")
        self.assertEqual(pdb.accession("PDB_1000AbCd"), "pdb_1000abcd")
        for value in ("0ABC", "ABCD", "1CRN/../x", "1CRN?x=y", "pdb_1234567", "1CRN\n", ""):
            with self.subTest(value=value), self.assertRaises(pdb.AccessError):
                pdb.accession(value)

    def test_experimental_only_and_bounded_pagination(self):
        query = pdb.search_query("crambin", 100, 5, "X-RAY DIFFRACTION",
                                 "2000-01-01", "2020-12-31")
        self.assertEqual(query["return_type"], "entry")
        options = query["request_options"]
        self.assertEqual(options["results_content_type"], ["experimental"])
        self.assertEqual(options["paginate"], {"start": 400, "rows": 100})
        self.assertNotIn("return_all_hits", options)
        nodes = query["query"]["nodes"]
        self.assertEqual(query["query"]["logical_operator"], "and")
        self.assertIn({"attribute": "rcsb_entry_info.structure_determination_methodology",
                       "operator": "exact_match", "value": "experimental"},
                      [node["parameters"] for node in nodes])
        self.assertIn({"attribute": "exptl.method", "operator": "exact_match",
                       "value": "X-RAY DIFFRACTION"}, [node["parameters"] for node in nodes])
        self.assertEqual(nodes[-1]["parameters"]["operator"], "less_or_equal")

    def test_invalid_query_limits_fail_before_network(self):
        cases = ({"rows": 101}, {"rows": 0}, {"page": 6}, {"page": 0},
                 {"rows": True}, {"after": "2020-02-30"},
                 {"after": "2020-01-02", "before": "2020-01-01"}, {"method": " "})
        for case in cases:
            with self.subTest(case=case), self.assertRaises(pdb.AccessError):
                pdb.search_query("crambin", **case)
        with self.assertRaises(pdb.AccessError):
            pdb.search_query("x" * 257)

    def test_page_limit_reports_remaining_results(self):
        raw = json.dumps({"total_count": 6, "result_set": [{"identifier": "1CRN"}]}).encode()
        def fetcher(url, limits, cap, payload):
            return raw, {"http_status": 200}
        saved, manifest = pdb.search("crambin", pdb.Limits(), rows=1, page=5, fetcher=fetcher)
        self.assertEqual(saved, raw)
        self.assertTrue(manifest["has_more"])
        self.assertTrue(manifest["truncated_by_page_limit"])
        self.assertIsNone(manifest["next_page"])

    def test_204_is_empty_success_but_malformed_200_is_error(self):
        def empty(url, limits, cap, payload):
            return b"", {"http_status": 204}
        raw, manifest = pdb.search("crambin", pdb.Limits(), fetcher=empty)
        self.assertEqual(raw, b"")
        self.assertEqual(manifest["identifiers"], [])
        self.assertEqual(manifest["total_count"], 0)
        for document in ({}, {"total_count": -1, "result_set": []},
                         {"total_count": 1, "result_set": [{"identifier": "AF-model"}]},
                         {"total_count": 2, "result_set": [{"identifier": "1CRN"}] * 2}):
            def malformed(url, limits, cap, payload):
                return json.dumps(document).encode(), {"http_status": 200}
            with self.subTest(document=document), self.assertRaises(pdb.AccessError):
                pdb.search("crambin", pdb.Limits(), rows=1, fetcher=malformed)


class TransportTests(unittest.TestCase):
    def test_byte_hash_and_raw_preservation(self):
        raw = b'{ "value": null }\n'
        response = Response(raw, headers={"Content-Length": str(len(raw)), "ETag": "fixture"})
        opener = Opener(response)
        saved, provenance = pdb.fetch(pdb.SEARCH_URL, pdb.Limits(), 1024, {"query": {}}, opener=opener)
        self.assertEqual(saved, raw)
        self.assertEqual(provenance["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(provenance["bytes"], len(raw))
        self.assertEqual(provenance["etag"], "fixture")
        self.assertTrue(provenance["retrieved_at_utc"].endswith("+00:00"))
        self.assertEqual(opener.calls[0][1], 20)
        self.assertEqual(opener.calls[0][0].get_method(), "POST")

    def test_declared_and_streamed_caps(self):
        declared = Response(b"abcd", headers={"Content-Length": "4"})
        with self.assertRaises(pdb.AccessError):
            pdb.fetch(pdb.SEARCH_URL, pdb.Limits(), 3, opener=Opener(declared))
        self.assertEqual(declared.read_calls, 0)
        streamed = Response(b"abcd")
        with self.assertRaises(pdb.AccessError):
            pdb.fetch(pdb.SEARCH_URL, pdb.Limits(), 3, opener=Opener(streamed))
        self.assertEqual(streamed.read_calls, 1)

    def test_deadline_checked_during_read(self):
        ticks = iter([0, 0, 31])
        with self.assertRaises(pdb.AccessError):
            pdb.fetch(pdb.SEARCH_URL, pdb.Limits(), 1024, opener=Opener(Response(b"{}")),
                      monotonic=lambda: next(ticks))

    def test_redirect_and_nonofficial_requests_refused(self):
        for url in ("http://search.rcsb.org/", "https://example.org/a", pdb.ENTRY_BASE + "1CRN/extra",
                    pdb.CIF_BASE + "1CRN.cif?token=x"):
            opener = Opener(Response())
            with self.subTest(url=url), self.assertRaises(pdb.AccessError):
                pdb.fetch(url, pdb.Limits(), 1024, opener=opener)
            self.assertEqual(opener.calls, [])
        handler = pdb.NoRedirect()
        with self.assertRaises(pdb.AccessError):
            handler.redirect_request(None, None, 302, "Found", {}, "https://example.org")
        with self.assertRaises(pdb.AccessError):
            pdb.fetch(pdb.SEARCH_URL, pdb.Limits(), 1024,
                      opener=Opener(Response(url="https://example.org")))

    def test_bad_transfer_and_http_errors_do_not_retry(self):
        for response in (Response(b"{}", headers={"Content-Length": "3"}),
                         Response(b"{}", headers={"Content-Length": "invalid"}),
                         Response(b"{}", headers={"Content-Encoding": "gzip"}),
                         Response(status=500), urllib.error.URLError("fixture timeout")):
            opener = Opener(response)
            with self.subTest(response=response), self.assertRaises(pdb.AccessError):
                pdb.fetch(pdb.SEARCH_URL, pdb.Limits(), 1024, opener=opener)
            self.assertEqual(len(opener.calls), 1)

    def test_interrupted_read_has_controlled_error(self):
        class InterruptedResponse(Response):
            def read(self, size=-1):
                raise http.client.IncompleteRead(b"partial", 10)
        opener = Opener(InterruptedResponse())
        with self.assertRaises(pdb.AccessError):
            pdb.fetch(pdb.SEARCH_URL, pdb.Limits(), 1024, opener=opener)
        self.assertEqual(len(opener.calls), 1)

    def test_json_cannot_use_coordinate_byte_budget(self):
        opener = Opener(Response())
        with self.assertRaises(pdb.AccessError):
            pdb.fetch(pdb.SEARCH_URL, pdb.Limits(), 3 * pdb.MIB, opener=opener)
        self.assertEqual(opener.calls, [])

    def test_hard_limits_and_strict_json(self):
        for values in ({"timeout": 61}, {"deadline": 121}, {"timeout": float("nan")},
                       {"json_bytes": 8 * pdb.MIB + 1}, {"cif_bytes": 0}):
            with self.subTest(values=values), self.assertRaises(pdb.AccessError):
                pdb.Limits(**values)
        for raw in (b"[]", b"<html>", b'{"v": NaN}', b'{"v": 1e999}'):
            with self.subTest(raw=raw), self.assertRaises(pdb.AccessError):
                pdb.decode_json(raw)


class EntryAndArtifactTests(unittest.TestCase):
    def test_null_missing_and_unknowns_preserved(self):
        fetcher, calls = fixture_fetch()
        metadata, cif, manifest = pdb.get_entry("pdb_00001crn", pdb.Limits(), fetcher=fetcher)
        document = json.loads(metadata)
        self.assertEqual(document["unknown_future_field"], ENTRY_FIXTURE["unknown_future_field"])
        self.assertEqual(cif, CIF_FIXTURE)
        summary = manifest["summary"]
        self.assertIsNone(summary["values"]["rcsb_entry_info.resolution_combined"])
        self.assertNotIn("rcsb_entry_info.resolution_combined", summary["missing_fields"])
        self.assertIn("pdbx_audit_revision_history", summary["missing_fields"])
        self.assertEqual(manifest["normalized_accession"], "pdb_00001crn")
        self.assertEqual(manifest["service_accession"], "1CRN")
        self.assertEqual(calls[0][0], pdb.ENTRY_BASE + "1CRN")
        self.assertEqual(calls[1][0], pdb.CIF_BASE + "1CRN.cif")

    def test_unverified_or_nonexperimental_metadata_stops_coordinate_fetch(self):
        documents = ({"rcsb_id": "1CRN"},
                     {**ENTRY_FIXTURE, "rcsb_entry_info": {"structure_determination_methodology": None}},
                     {**ENTRY_FIXTURE, "rcsb_entry_info": {"structure_determination_methodology": "integrative"}},
                     {**ENTRY_FIXTURE, "rcsb_entry_info": {"structure_determination_methodology": "computational"}},
                     {**ENTRY_FIXTURE, "rcsb_id": "4HHB"})
        for document in documents:
            fetcher, calls = fixture_fetch(document)
            with self.subTest(document=document), self.assertRaises(pdb.AccessError):
                pdb.get_entry("1CRN", pdb.Limits(), fetcher=fetcher)
            self.assertEqual(len(calls), 1)

    def test_cif_sanity_check_does_not_parse_or_modify(self):
        for raw in (b"<html>Error</html>", b"", b"\xff"):
            fetcher, calls = fixture_fetch(raw_cif=raw)
            with self.subTest(raw=raw), self.assertRaises(pdb.AccessError):
                pdb.get_entry("1CRN", pdb.Limits(), fetcher=fetcher)
            self.assertEqual(len(calls), 2)

    def test_existing_artifacts_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            pdb.save_artifacts(directory, {"raw.cif": b"first"})
            with self.assertRaises(pdb.AccessError):
                pdb.save_artifacts(directory, {"raw.cif": b"second", "manifest.json": b"{}"})
            self.assertEqual((directory / "raw.cif").read_bytes(), b"first")
            self.assertFalse((directory / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
