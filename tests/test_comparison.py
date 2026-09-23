import unittest

from explanations import compare_dates
from test_explanations import QUERY, profile


class ComparisonTests(unittest.TestCase):
    def test_busy_profile_and_replacement_have_different_reasons(self):
        rows = [profile(str(i), price_from_kzt=i * 10000) for i in range(1, 5)]
        rows[0]["busy_dates"] = ["2026-10-02"]
        result = compare_dates(rows, QUERY, "2026-10-02")
        changes = {item["id"]: item for item in result["changes"]}
        self.assertEqual(set(changes), {"1", "4"})
        self.assertEqual(changes["1"]["states"][1]["codes"], ["date_busy"])
        self.assertIn("занята по календарю", changes["1"]["message"])
        self.assertEqual(changes["4"]["states"][0]["codes"], ["outside_top_3"])
        self.assertIn("ниже первой тройки", changes["4"]["message"])
        self.assertEqual(result, compare_dates(rows[::-1], QUERY, "2026-10-02"))

    def test_calendar_unknown_is_not_called_busy(self):
        row = profile(calendar_range={"start": "2026-10-01", "end": "2026-10-31"})
        result = compare_dates([row], QUERY, "2026-11-01")
        self.assertEqual(result["changes"][0]["states"][1]["codes"], ["date_outside_calendar"])
        self.assertIn("нет данных календаря", result["changes"][0]["message"])

    def test_same_date_and_empty_results_are_explained(self):
        same = compare_dates([profile()], QUERY, QUERY["date"])
        self.assertEqual(same["changes"], [])
        self.assertEqual(same["results"][0], same["results"][1])
        self.assertIn("одинаковый", same["message"])
        empty = compare_dates([], QUERY, "2026-10-02")
        self.assertEqual(empty["changes"], [])
        self.assertIn("нет подходящих", empty["message"])


if __name__ == "__main__":
    unittest.main()
