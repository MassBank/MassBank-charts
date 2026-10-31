import unittest
from decimal import Decimal

from compare_primary_data import api_fields, primary_fields, source_date


class PrimaryDataTests(unittest.TestCase):
    def test_allowed_dates_do_not_invent_history(self):
        self.assertEqual(source_date("2025.01.17"), {"updated": "2025-01-17"})
        self.assertEqual(source_date("2012.10.22 (Created 2008.05.12)"),
                         {"updated": "2012-10-22", "created": "2008-05-12"})
        self.assertEqual(source_date("2016.01.19 (Created 2006.12.21, modified 2011.05.06)"),
                         {"updated": "2016-01-19", "created": "2006-12-21", "modified": "2011-05-06"})
        for invalid in ("2025.02.29", "2025.01.17 trailing", "2025.01.17 (modified 2024.01.01)"):
            with self.assertRaises(ValueError):
                source_date(invalid)

    def test_primary_numeric_values_classes_and_headers(self):
        source = """ACCESSION: MSBNK-Test-A1
DATE: 2025.01.17
COPYRIGHT: Test
CH$COMPOUND_CLASS: Natural Product; Lipid Standard
PK$NUM_PEAK: 1
PK$PEAK: m/z int. rel.int.
  107.0400 1.0e3 999
//
"""
        expected = primary_fields(source)
        actual = api_fields({
            "date": {"updated": "2025-01-17"}, "copyright": "Test",
            "compound": {"classes": ["Natural Product", "Lipid Standard"]},
            "peak": {"numPeak": 1, "peak": {
                "header": ["m/z", "int.", "rel.int."],
                "values": [{"id": 123, "mz": 107.04, "intensity": 1000, "rel": 999}],
            }},
        })
        self.assertEqual(expected, actual)
        actual["peaks"][0][0] = Decimal("107.04000091552734")
        self.assertNotEqual(expected["peaks"], actual["peaks"])

    def test_missing_peak_value_is_not_treated_as_source_zero(self):
        actual = api_fields({
            "date": {"updated": "2025-01-17"}, "compound": {},
            "peak": {"numPeak": 1, "peak": {
                "values": [{"mz": 107.04, "intensity": 1}],
            }},
        })
        self.assertEqual(actual["peaks"][0][2], "<missing>")

    def test_malformed_source_is_not_silently_skipped(self):
        for text in ("DEPRECATED: 2025-01-17\n", "ACCESSION: MSBNK-Test-A1\n"):
            with self.assertRaises(ValueError):
                primary_fields(text)


if __name__ == "__main__":
    unittest.main()
