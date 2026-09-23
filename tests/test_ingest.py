import json
from pathlib import Path
import tempfile
import unittest

from ingest import prepare, read_csv, read_preview
from matching import normalize_profiles, select_candidates

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "data/source/profiles.csv"
HTML = ROOT / "data/source/preview.html"


class IngestTests(unittest.TestCase):
    def test_real_sources_and_round_trip(self):
        profiles, report = prepare(CSV, HTML)
        self.assertEqual(len(profiles), 66)
        self.assertTrue(report["same_ids"])
        self.assertTrue(report["preview_consistent"])
        self.assertFalse(report["merged"])
        self.assertEqual(profiles, normalize_profiles(json.loads(json.dumps(profiles))))

    def test_real_selection_and_calendar_bounds(self):
        profiles, _ = prepare(CSV, HTML)
        query = json.loads((ROOT / "examples/dataset_request.json").read_text(encoding="utf-8"))
        result = select_candidates(profiles, query)
        self.assertEqual(len(result["candidates"]), 2)
        ids = [x["profile"]["id"] for x in result["candidates"]] + [x["id"] for x in result["rejected"]]
        self.assertEqual(len(ids), 66)
        self.assertEqual(len(set(ids)), 66)
        outside = select_candidates(profiles, dict(query, date="2027-01-01"))
        self.assertFalse(outside["candidates"])
        self.assertTrue(all(any(r["code"] == "date_outside_calendar" for r in p["reasons"]) for p in outside["rejected"]))

    def test_preview_conflict_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preview.html"
            path.write_text(HTML.read_text(encoding="utf-8").replace("200 000 ₸", "200 001 ₸", 1), encoding="utf-8")
            _, report = prepare(CSV, path)
            self.assertFalse(report["preview_consistent"])
            self.assertEqual(report["conflicts"][0]["id"], "HK-39372")
            self.assertIn("price", report["conflicts"][0]["fields"])

    def test_invalid_inputs_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.csv"
            path.write_text("id,id\n1,2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_csv(path)
            path.write_text("<html>Пусто</html>", encoding="utf-8")
            with self.assertRaises(ValueError):
                read_preview(path)


if __name__ == "__main__":
    unittest.main()
