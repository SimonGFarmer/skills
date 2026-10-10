"""Offline synthetic response tests; they do not claim live ESA compatibility."""

import importlib.util
import io
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fetch_gaia", ROOT / "scripts" / "fetch_gaia.py")
gaia = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gaia)
FIXTURE = Path(__file__).parent / "fixtures" / "field.xml"
NS = {"v": "http://www.ivoa.net/xml/VOTable/v1.3"}


class VOTableTests(unittest.TestCase):
    def setUp(self):
        self.raw = FIXTURE.read_bytes()

    def mutate_cell(self, name, value):
        root = ET.fromstring(self.raw)
        table = root.find("v:RESOURCE/v:TABLE", NS)
        names = [field.attrib["name"] for field in table.findall("v:FIELD", NS)]
        cells = table.find("v:DATA/v:TABLEDATA/v:TR", NS)
        cells[names.index(name)].text = value
        return ET.tostring(root)

    def test_large_ids_negative_parallax_nulls_and_metadata(self):
        result = gaia.parse_votable(self.raw, 10)
        first, second = result["rows"]
        self.assertEqual(first["source_id"], "1234567890123456789")
        self.assertEqual(first["parallax"], -0.8)
        self.assertIsNone(first["bp_rp"])
        self.assertIsNone(second["parallax"])
        self.assertEqual(first["pmra"], 12.5)
        self.assertEqual(result["reported_fields"][2]["unit"], "deg")
        self.assertFalse(result["incomplete"])

    def test_extra_row_reports_selection_omission(self):
        result = gaia.parse_votable(self.raw, 1)
        self.assertEqual(result["included_rows"], 1)
        self.assertEqual(result["returned_rows"], 2)
        self.assertTrue(result["selection_limited"])
        self.assertTrue(result["incomplete"])

    def test_trailing_status_changes_outcome(self):
        for status in ("ERROR", "OVERFLOW"):
            raw = self.raw.replace(b"</RESOURCE>", f'<INFO name="QUERY_STATUS" value="{status}"/></RESOURCE>'.encode())
            if status == "ERROR":
                with self.assertRaises(gaia.GaiaError):
                    gaia.parse_votable(raw, 10)
            else:
                result = gaia.parse_votable(raw, 10)
                self.assertTrue(result["service_overflow"])
                self.assertTrue(result["incomplete"])

    def test_invalid_scientific_values_fail(self):
        for name, value in (("pmra", "NaN"), ("ra", "360"), ("dec", "91"),
                            ("pmra_pmdec_corr", "1.01"), ("parallax_error", "-1"),
                            ("source_id", "1.234e18"), ("pmdec", ""), ("ruwe", "-1")):
            with self.subTest(name=name), self.assertRaises(gaia.GaiaError):
                gaia.parse_votable(self.mutate_cell(name, value), 10)

    def test_byte_cap_malformed_xml_and_entity_declarations(self):
        for raw, cap in ((self.raw, 1), (b"<VOTABLE>", 100),
                         (b'<!DOCTYPE VOTABLE [<!ENTITY x "data">]><VOTABLE/>', 100)):
            with self.assertRaises(gaia.GaiaError):
                gaia.parse_votable(raw, 10, cap)

    def test_utf16_declarations_cannot_bypass_utf8_contract(self):
        raw = '<!DOCTYPE VOTABLE [<!ENTITY x "data">]><VOTABLE/>'.encode('utf-16')
        with self.assertRaisesRegex(gaia.GaiaError, 'UTF-8'):
            gaia.parse_votable(raw, 10)
        for encoding in ('utf-16-le', 'utf-16-be'):
            with self.assertRaisesRegex(gaia.GaiaError, 'UTF-8'):
                gaia.parse_votable('<VOTABLE/>'.encode(encoding), 10)

    def test_binary_serialization_is_explicit_failure(self):
        root = ET.fromstring(self.raw)
        data = root.find("v:RESOURCE/v:TABLE/v:DATA", NS)
        data.clear()
        ET.SubElement(data, "BINARY2")
        with self.assertRaisesRegex(gaia.GaiaError, "TABLEDATA"):
            gaia.parse_votable(ET.tostring(root), 10)

    def test_declared_null_sentinel_and_wrong_units(self):
        root = ET.fromstring(self.raw)
        fields = root.findall("v:RESOURCE/v:TABLE/v:FIELD", NS)
        field = next(field for field in fields if field.attrib["name"] == "parallax")
        ET.SubElement(field, "VALUES", {"null": "-0.8"})
        result = gaia.parse_votable(ET.tostring(root), 10)
        self.assertIsNone(result["rows"][0]["parallax"])
        field.set("unit", "arcsec")
        with self.assertRaisesRegex(gaia.GaiaError, "unit disagrees"):
            gaia.parse_votable(ET.tostring(root), 10)

    def test_missing_status_schema_and_excess_rows_fail(self):
        without_status = self.raw.replace(b'<INFO name="QUERY_STATUS" value="OK"/>', b"")
        wrong_field = self.raw.replace(b'name="pmra"', b'name="wrong"')
        root = ET.fromstring(self.raw)
        tabledata = root.find("v:RESOURCE/v:TABLE/v:DATA/v:TABLEDATA", NS)
        tabledata.append(ET.fromstring(ET.tostring(tabledata[0])))
        for raw in (without_status, wrong_field, ET.tostring(root)):
            with self.assertRaises(gaia.GaiaError):
                gaia.parse_votable(raw, 1)


class BoundsAndReceiptTests(unittest.TestCase):
    def test_input_bounds_and_explicit_query(self):
        query = gaia.build_query(56.75, 24.12, 0.1, 100)
        self.assertIn("SELECT TOP 101", query)
        self.assertIn("gaiadr3.gaia_source", query)
        self.assertIn("ORDER BY phot_g_mean_mag ASC, source_id ASC", query)
        for args in ((360, 0, 0.1, 10, 30, 1024), (0, 91, 0.1, 10, 30, 1024),
                     (0, 0, 0, 10, 30, 1024), (0, 0, 1.1, 10, 30, 1024),
                     (0, 0, 0.1, 1001, 30, 1024), (0, 0, 0.1, 10, 31, 1024),
                     (0, 0, 0.1, 10, 30, gaia.MAX_BYTES + 1)):
            with self.assertRaises(gaia.GaiaError):
                gaia.validate_inputs(*args)

    def test_redirect_scope(self):
        for url in ("https://example.com/tap-server/result", "http://gea.esac.esa.int/tap-server/result",
                    "https://gea.esac.esa.int/other/result", "https://user@gea.esac.esa.int/tap-server/result"):
            with self.assertRaises(gaia.GaiaError):
                gaia.allowed_url(url)
        gaia.allowed_url("https://gea.esac.esa.int/tap-server/tap/async/1/results/result")

    def test_stream_byte_cap_and_deadline(self):
        response = Mock()
        response.getheader.side_effect = lambda key, default=None: default
        response.read1.side_effect = [b"1234", b"56", b""]
        with self.assertRaises(gaia.GaiaError):
            gaia.read_bounded(response, Mock(), time.monotonic() + 10, 5)
        with self.assertRaises(gaia.GaiaError):
            gaia.remaining(time.monotonic() - 1)

    def test_provenance_and_file_refuses_overwrite(self):
        with patch.object(gaia, "fetch_xml", return_value=(FIXTURE.read_bytes(), gaia.ENDPOINT)) as fetch:
            result = gaia.retrieve(56.75, 24.12, 0.1, 10)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(result["provenance"]["table"], "gaiadr3.gaia_source")
            self.assertIn("SELECT TOP 11", result["provenance"]["query"])
            self.assertFalse(result["selection"]["membership_claim"])
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "existing.json"
            out.write_text("keep", encoding="utf-8")
            with patch.object(gaia, "retrieve") as retrieve, patch("sys.stderr", new=io.StringIO()):
                code = gaia.main(["--ra", "56.75", "--dec", "24.12", "--radius", "0.1", "--out", str(out)])
            self.assertEqual(code, 1)
            self.assertEqual(out.read_text(encoding="utf-8"), "keep")
            retrieve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
