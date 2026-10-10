import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "qgis_mcp_plugin"))
from csv_profile import profile_csv


class CsvProfileTests(unittest.TestCase):
    def test_complete_counts_ranges_and_nonfinite_are_facts_not_guessed_roles(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder, "survey.csv")
            source.write_text("x;z;code\n1;12;7\n2;14;9\n3;;7\n4;NaN;9\n", encoding="utf-8-sig")
            result = profile_csv(source, has_header=True)
            self.assertEqual(result["row_count"], 4)
            self.assertEqual(result["delimiter"], ";")
            self.assertEqual(result["fields"]["code"]["value_counts"], {"7": 2, "9": 2})
            self.assertEqual(result["fields"]["z"]["missing"], 1)
            self.assertEqual(result["fields"]["z"]["non_finite_count"], 1)
            self.assertEqual(result["fields"]["z"]["max"], 14)
            self.assertNotIn("crs", result)

    def test_large_cardinality_is_not_reported_as_complete_distribution(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder, "survey.csv")
            source.write_text("id,z\n" + "".join(f"{i},{i * 2}\n" for i in range(120)))
            result = profile_csv(source, ",", has_header=True)
            self.assertEqual(result["row_count"], 120)
            self.assertEqual(result["fields"]["id"]["value_counts"], {})
            self.assertFalse(result["fields"]["id"]["value_counts_complete"])
            self.assertEqual(len(result["preview"]), 5)

    def test_malformed_rows_and_duplicate_headers_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder, "bad.csv")
            for text in ("x,x\n1,2\n", "x,z\n1,2,3\n"):
                source.write_text(text)
                with self.assertRaises(ValueError):
                    profile_csv(source, ",", has_header=True)

    def test_headerless_survey_counts_first_record_and_preserves_column_order(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder, "survey.csv")
            source.write_text("1;222538.1;103486.2;79.8;1\n2;222539;103487;80;3\n3;222540;103488;81;1\n", encoding="utf-8-sig")
            result = profile_csv(source, has_header=False, column_names=["id", "x", "y", "z", "code"])
            self.assertFalse(result["has_header"])
            self.assertEqual(result["row_count"], 3)
            self.assertEqual(result["columns"], ["id", "x", "y", "z", "code"])
            self.assertEqual(result["fields"]["code"]["value_counts"], {"1": 2, "3": 1})
            self.assertEqual(result["fields"]["z"]["min"], 79.8)
            self.assertEqual(result["preview"][0]["id"], "1")

    def test_headerless_text_data_gets_neutral_names_without_guessing(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder, "labels.csv")
            source.write_text('"first,label",7\nsecond,9\n')
            result = profile_csv(source, ",", has_header=False)
            self.assertEqual(result["columns"], ["column_1", "column_2"])
            self.assertEqual(result["row_count"], 2)
            self.assertEqual(result["preview"][0]["column_1"], "first,label")

    def test_header_mode_and_column_names_must_be_explicit_and_consistent(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder, "survey.csv")
            source.write_text("1,2\n3,4\n")
            with self.assertRaisesRegex(ValueError, "CSV_HEADER_MODE_REQUIRED"):
                profile_csv(source, ",")
            for options in ({"has_header": "false"}, {"has_header": 0},
                            {"has_header": False, "column_names": ["x"]},
                            {"has_header": False, "column_names": ["x", " x "]},
                            {"has_header": False, "column_names": ["x", ""]},
                            {"has_header": False, "column_names": "x,y"},
                            {"has_header": True, "column_names": ["x", "y"]}):
                with self.assertRaises(ValueError):
                    profile_csv(source, ",", **options)

    def test_empty_header_only_and_malformed_headerless_files(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder, "survey.csv")
            source.write_text("")
            with self.assertRaisesRegex(ValueError, "no records"):
                profile_csv(source, ",", has_header=False)
            source.write_text("x,z\n")
            self.assertEqual(profile_csv(source, ",", has_header=True)["row_count"], 0)
            self.assertEqual(profile_csv(source, ",", has_header=False)["row_count"], 1)
            source.write_text("\n1,2\n3,4,5\n")
            with self.assertRaisesRegex(ValueError, "row 3"):
                profile_csv(source, ",", has_header=False)
