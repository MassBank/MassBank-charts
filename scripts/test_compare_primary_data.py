import unittest
from decimal import Decimal

from compare_primary_data import api_fields, order_only, primary_fields, source_date, subtag_text_equal


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

    def test_all_fields_and_column_major_annotations(self):
        source = """ACCESSION: MSBNK-Test-A1
RECORD_TITLE: Test; ESI-QTOF; MS2
DATE: 2025.01.17
AUTHORS: One [dtc], Two [com]
LICENSE: CC0
COPYRIGHT: Test
PUBLICATION: Reference
PROJECT: Project
COMMENT: CONFIDENCE Reference standard
COMMENT: Free text
COMMENT:   literal  "text", \\ slash
COMMENT: Free text
CH$NAME: Test
CH$COMPOUND_CLASS: Natural Product; Lipid Standard
CH$FORMULA: CH4
CH$EXACT_MASS: 16.0313
CH$SMILES: C
CH$IUPAC: InChI=1S/CH4/h1H4
CH$LINK: PUBCHEM CID:297
SP$SCIENTIFIC_NAME: Species
SP$LINEAGE: A; B
SP$LINK: TAXON 123
SP$SAMPLE: Leaf
AC$INSTRUMENT: Instrument
AC$INSTRUMENT_TYPE: ESI-QTOF
AC$MASS_SPECTROMETRY: MS_TYPE MS2
AC$MASS_SPECTROMETRY: ION_MODE POSITIVE
AC$MASS_SPECTROMETRY: COLLISION_ENERGY 10
AC$CHROMATOGRAPHY: SOLVENT A water
AC$CHROMATOGRAPHY: SOLVENT B methanol
AC$GENERAL: GENERAL Example
AC$ION_MOBILITY: CCS 100
MS$FOCUSED_ION: PRECURSOR_M/Z 17
MS$DATA_PROCESSING: WHOLE Test
PK$SPLASH: splash-test
PK$ANNOTATION: m/z formula
  15.000 CH3+
PK$NUM_PEAK: 1
PK$PEAK: m/z int. rel.int.
  15.000 1000 999
//
"""
        record = {
            "accession": "MSBNK-Test-A1", "title": "Test; ESI-QTOF; MS2",
            "date": {"updated": "2025-01-17"},
            "authors": [{"name": "One", "marc-relator": "dtc"}, {"name": " Two", "marc-relator": "com"}],
            "license": "CC0", "copyright": "Test", "publication": "Reference", "project": "Project",
            "comments": ["CONFIDENCE Reference standard", "Free text", '  literal  "text", \\ slash', "Free text"],
            "compound": {"names": ["Test"], "classes": ["Natural Product", "Lipid Standard"],
                         "formula": "CH4", "mass": 16.0313, "smiles": "C", "inchi": "InChI=1S/CH4/h1H4",
                         "link": [{"database": "PUBCHEM", "identifier": "CID:297"}]},
            "species": {"name": "Species", "lineage": ["A", "B"],
                        "link": [{"database": "TAXON", "identifier": "123"}], "sample": ["Leaf"]},
            "acquisition": {
                "instrument": "Instrument", "instrument_type": "ESI-QTOF",
                "mass_spectrometry": {"ms_type": "MS2", "ion_mode": "POSITIVE",
                                      "subtags": [{"subtag": "COLLISION_ENERGY", "value": "10"}]},
                "chromatography": [{"subtag": "SOLVENT", "value": "A water"}, {"subtag": "SOLVENT", "value": "B methanol"}],
                "general": [{"subtag": "GENERAL", "value": "Example"}],
                "ion_mobility": [{"subtag": "CCS", "value": "100"}],
            },
            "mass_spectrometry": {"focused_ion": [{"subtag": "PRECURSOR_M/Z", "value": "17"}],
                                 "data_processing": [{"subtag": "WHOLE", "value": "Test"}]},
            "peak": {"splash": "splash-test", "numPeak": 1,
                     "annotation": {"header": ["m/z", "formula"], "values": [["15"], ["CH3+"]]},
                     "peak": {"header": ["m/z", "int.", "rel.int."],
                              "values": [{"id": 321, "mz": 15, "intensity": 1000, "rel": 999}]}},
        }
        expected = primary_fields(source, all_fields=True)
        actual = api_fields(record, all_fields=True)
        self.assertEqual(expected, actual)
        record["peak"]["annotation"] = {"header": ["formula", "m/z"], "values": [["CH3+"], ["15"]]}
        reordered = api_fields(record, all_fields=True)
        self.assertEqual(reordered["annotation.rows"], [["CH3+", Decimal("15")]])
        self.assertNotEqual(expected["annotation.header"], reordered["annotation.header"])
        record["peak"]["annotation"] = {"header": ["m/z", "formula"], "values": [["15"], ["CH3+"]]}
        record["comments"][0] = {"subtag": "CONFIDENCE", "value": "Reference standard"}
        self.assertNotEqual(expected["comments"], api_fields(record, all_fields=True)["comments"])
        del record["comments"]
        record["authors"][0] = {"name": "One [dtc]"}
        actual = api_fields(record, all_fields=True)
        self.assertNotEqual(expected["comments"], actual["comments"])
        self.assertEqual(expected["authors.text"], actual["authors.text"])
        self.assertNotEqual(expected["authors.roles"], actual["authors.roles"])
        record["peak"]["annotation"]["values"] = [["15"]]
        self.assertIn("malformed_api_columns", api_fields(record, all_fields=True)["annotation.rows"])
        unknown = primary_fields(source.replace("CH$FORMULA:", "NEW_TAG: value\nCH$FORMULA:"), all_fields=True)
        self.assertEqual(unknown["unmapped_source_fields"], {"NEW_TAG": ["value"]})

    def test_order_diagnostics_preserve_duplicates_and_decimal_equality(self):
        self.assertTrue(order_only([["x", Decimal("1.00")], ["y", Decimal("2")]],
                                   [["y", Decimal("2.0")], ["x", Decimal("1")]]))
        self.assertFalse(order_only(["x", "x", "y"], ["x", "y", "y"]))

    def test_multiword_legacy_subtags_do_not_imply_data_loss(self):
        self.assertTrue(subtag_text_equal(
            [["INTENSITY", "CUTOFF 0.05 Base Peak"]],
            [["INTENSITY CUTOFF", "0.05 Base Peak"]]))
        self.assertFalse(subtag_text_equal(
            [["INTENSITY", "CUTOFF 0.05 Base Peak"]],
            [["INTENSITY CUTOFF", "0.5 Base Peak"]]))
        self.assertFalse(subtag_text_equal(["Free text"], []))


if __name__ == "__main__":
    unittest.main()
