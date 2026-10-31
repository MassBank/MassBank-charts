from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from compare_all_primary_data import compare_record, run, source_index, source_values, value_differences
from compare_apis import Response


SOURCE = """ACCESSION: MSBNK-Test-A1
RECORD_TITLE: Test; MS2
DATE: 2025.01.17
AUTHORS: Author [dtc]
LICENSE: CC0
COMMENT: CONFIDENCE  Predicted
COMMENT: duplicated
COMMENT: duplicated
CH$NAME: Test
CH$COMPOUND_CLASS: Standard
CH$FORMULA: CH4
CH$EXACT_MASS: 16.0313
CH$SMILES: C
CH$IUPAC: InChI=1S/CH4/h1H4
AC$INSTRUMENT: Instrument
AC$INSTRUMENT_TYPE: ESI-QTOF
AC$MASS_SPECTROMETRY: MS_TYPE MS2
AC$MASS_SPECTROMETRY: ION_MODE POSITIVE
PK$SPLASH: splash-test
PK$NUM_PEAK: 1
PK$PEAK: m/z int. rel.int.
  15.000 1000 0
//
"""


def record(accession="MSBNK-Test-A1"):
    return {
        "accession": accession, "title": "Test; MS2", "date": {"updated": "2025-01-17"},
        "authors": [{"name": "Author [dtc]"}], "license": "CC0",
        "comments": ["CONFIDENCE  Predicted", "duplicated", "duplicated"],
        "compound": {"names": ["Test"], "classes": ["Standard"], "formula": "CH4",
                     "mass": Decimal("16.0313"), "smiles": "C", "inchi": "InChI=1S/CH4/h1H4"},
        "acquisition": {"instrument": "Instrument", "instrument_type": "ESI-QTOF",
                        "mass_spectrometry": {"ms_type": "MS2", "ion_mode": "POSITIVE"}},
        "peak": {"splash": "splash-test", "numPeak": 1,
                 "peak": {"header": ["m/z", "int.", "rel.int."],
                          "values": [{"id": 123, "mz": 15, "intensity": 1000, "rel": 0}]}},
    }


def response(data, status=200):
    return Response(status, 1, 100, "hash", data, None if status == 200 else f"HTTP {status}")


class ExhaustiveComparisonTests(unittest.TestCase):
    def test_exact_numeric_values_missing_tails_and_untruncated_strings(self):
        long_text = "literal" * 1000
        source = {"numbers": [Decimal("1.000"), Decimal("0.1234567890123456789")],
                  "comments": ["a", long_text], "missing": "original"}
        actual = {"numbers": [Decimal("1"), Decimal("0.1234567890123456788")],
                  "comments": ["a"], "extra": None}
        changes = list(value_differences(source, actual))
        self.assertEqual(len(changes), 4)
        self.assertEqual(changes[0]["source"], long_text)
        self.assertEqual(changes[-1]["source"], Decimal("0.1234567890123456789"))
        self.assertEqual(list(value_differences(1, True))[0]["api_type"], "bool")

    def test_all_fields_comments_and_explicit_marc_exclusion(self):
        expected = source_values(SOURCE, include_roles=False)
        self.assertNotIn("authors.roles", expected)
        self.assertEqual(compare_record(expected, response(record()))["outcome"], "matching")
        changed = record()
        changed["comments"].pop()
        result = compare_record(expected, response(changed))
        self.assertEqual(result["fields"]["comments"]["differences"][0]["source"], "duplicated")
        self.assertEqual(result["fields"]["comments"]["classification"], "value")
        with_roles = compare_record(source_values(SOURCE, True), response(record()))
        self.assertIn("authors.roles", with_roles["fields"])

    def test_order_and_text_preserving_splits_are_diagnosed_not_hidden(self):
        source = SOURCE.replace("PK$SPLASH:", "MS$DATA_PROCESSING: INTENSITY CUTOFF 0.05\nPK$SPLASH:")
        changed = record()
        changed["comments"].reverse()
        changed["mass_spectrometry"] = {"data_processing": [{"subtag": "INTENSITY CUTOFF", "value": "0.05"}]}
        result = compare_record(source_values(source, False), response(changed))
        self.assertEqual(result["fields"]["comments"]["classification"], "order_only")
        self.assertEqual(result["fields"]["mass_spectrometry.data_processing"]["classification"], "text_preserving_split")
        self.assertEqual(result["outcome"], "different")

    def test_deprecated_records_and_http_200_error_strings(self):
        source = "ACCESSION: MSBNK-Test-D1\nDEPRECATED: 2020-05-11 Wrong measurement\n"
        expected = source_values(source, False)
        self.assertEqual(compare_record(expected, response(expected), True)["outcome"], "matching")
        result = compare_record(expected, response("sql: no rows in result set"), True)
        self.assertEqual(result["outcome"], "error")
        self.assertIn("success-shaped", result["error"])
        self.assertEqual(compare_record(expected, response({}, 404), True)["outcome"], "error")
        self.assertEqual(compare_record(source_values(SOURCE, False), response({}))["outcome"], "error")

    def test_source_index_rejects_duplicate_and_misnamed_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "MSBNK-Test-A2.txt").write_text(SOURCE)
            with self.assertRaisesRegex(ValueError, "disagreement"):
                source_index(root)
            (root / "MSBNK-Test-A2.txt").unlink()
            (root / "MSBNK-Test-A1.txt").write_text(SOURCE)
            (root / "other").mkdir()
            (root / "other/MSBNK-Test-A1.txt").write_text(SOURCE)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                source_index(root)

    def test_union_complete_reports_resume_and_source_change_rejection(self):
        calls = []

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def get(self, endpoint):
                calls.append(endpoint)
                if endpoint == "/records/search":
                    return response({"data": [{"accession": "MSBNK-Test-A1"}, {"accession": "MSBNK-Test-X1"}]})
                if endpoint == "/records/count":
                    return response(2)
                if endpoint.endswith("D1"):
                    return response("sql: no rows in result set")
                if endpoint.endswith("A2"):
                    return response({}, 404)
                return response(record(endpoint.split("/")[-1]))

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as tmp, patch("compare_all_primary_data.Client", FakeClient):
            root = Path(tmp)
            sources = root / "sources"
            sources.mkdir()
            (sources / "MSBNK-Test-A1.txt").write_text(SOURCE)
            (sources / "MSBNK-Test-A2.txt").write_text(SOURCE.replace("Test-A1", "Test-A2"))
            (sources / "MSBNK-Test-D1.txt").write_text(
                "ACCESSION: MSBNK-Test-D1\nDEPRECATED: 2020-05-11 Wrong measurement\n")
            args = SimpleNamespace(source_data=sources, output=root / "report", resume=False,
                                   source_reference="fixture", api=[("test", "http://example.test")],
                                   timeout=1, delay=0, max_bytes=1000000, workers=2, include_marc_roles=False)
            self.assertEqual(run(args), 1)
            summary = json.loads((args.output / "summary.json").read_text())
            self.assertTrue(summary["complete"])
            self.assertEqual(summary["total_accessions"], 4)
            self.assertEqual(summary["inventory"]["test"]["missing_active"], ["MSBNK-Test-A2"])
            self.assertEqual(summary["inventory"]["test"]["not_in_source"], ["MSBNK-Test-X1"])
            self.assertEqual(summary["results"]["test"]["outcomes"], {"matching": 1, "error": 2, "missing_source": 1})
            self.assertEqual(len((args.output / "differences.jsonl").read_text().splitlines()), 3)
            # Resume must not repeat completed requests, including previously failed requests.
            db = sqlite3.connect(args.output / "results.sqlite")
            try:
                db.execute("DELETE FROM results WHERE accession='MSBNK-Test-A1'")
                db.commit()
            finally:
                db.close()
            calls.clear()
            args.resume = True
            self.assertEqual(run(args), 1)
            self.assertEqual([path for path in calls if path.startswith("/records/MSBNK")],
                             ["/records/MSBNK-Test-A1"])
            (sources / "MSBNK-Test-A1.txt").write_text(SOURCE.replace("Predicted", "Changed"))
            with self.assertRaisesRegex(ValueError, "Resume rejected"):
                run(args)


if __name__ == "__main__":
    unittest.main()
