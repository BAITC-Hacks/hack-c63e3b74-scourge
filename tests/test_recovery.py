import unittest

from explanations import recommend
from test_explanations import QUERY, profile


CALENDAR = {"start": "2026-09-23", "end": "2026-12-31"}


class RecoveryTests(unittest.TestCase):
    def assert_verified(self, rows, query, suggestions):
        for suggestion in suggestions:
            with self.subTest(field=suggestion["field"]):
                changed = {key for key in set(query) | set(suggestion["request"])
                           if query.get(key) != suggestion["request"].get(key)}
                self.assertEqual(changed, {suggestion["field"]})
                result = recommend(rows, suggestion["request"])
                self.assertEqual(result["status"], "matched")
                self.assertEqual(result["eligible_count"], suggestion["eligible_count"])

    def test_minimum_budget_preserves_all_other_conditions(self):
        rows = [profile("expensive", price_from_kzt=300000),
                profile("less_expensive", price_from_kzt=250000),
                profile("busy", price_from_kzt=230000, busy_dates=[QUERY["date"]])]
        original = QUERY.copy()
        result = recommend(rows, QUERY)
        self.assertEqual(QUERY, original)
        self.assertEqual([(s["field"], s["value"]) for s in result["suggestions"]],
                         [("budget", 250000)])
        self.assert_verified(rows, QUERY, result["suggestions"])

    def test_nearest_date_is_verified_and_future_wins_ties(self):
        rows = [profile(busy_dates=[QUERY["date"]], calendar_range=CALENDAR)]
        suggestions = recommend(rows, QUERY)["suggestions"]
        self.assertEqual(suggestions[0]["value"], "2026-10-02")
        self.assert_verified(rows, QUERY, suggestions)

    def test_calendar_end_and_explicit_availability(self):
        variants = [
            ([profile(busy_dates=["2026-12-31"], calendar_range=CALENDAR)],
             dict(QUERY, date="2026-12-31"), "2026-12-30"),
            ([profile(available_dates=["2026-10-04"])], QUERY, "2026-10-04"),
        ]
        for rows, query, expected in variants:
            with self.subTest(expected=expected):
                suggestions = recommend(rows, query)["suggestions"]
                self.assertEqual(suggestions[0]["value"], expected)
                self.assert_verified(rows, query, suggestions)

    def test_no_invented_calendar_or_distant_dates(self):
        for row in (profile(busy_dates=[QUERY["date"]]),
                    profile(available_dates=["2026-10-09"])):
            with self.subTest(row=row):
                self.assertEqual(recommend([row], QUERY)["suggestions"], [])

    def test_no_false_promise_when_two_conditions_block(self):
        rows = [profile(price_from_kzt=300000, languages=["английский"])]
        result = recommend(rows, QUERY)
        self.assertEqual(result["suggestions"], [])
        self.assertIn("сочетание условий", result["recovery_message"])

    def test_optional_conditions_can_be_changed_separately(self):
        rows = [profile("language", languages=["английский"]),
                profile("hours", max_hours=4)]
        suggestions = recommend(rows, QUERY)["suggestions"]
        self.assertEqual({s["field"] for s in suggestions}, {"language", "duration_hours"})
        self.assert_verified(rows, QUERY, suggestions)

    def test_absent_category_and_matches_need_no_recovery(self):
        for rows in ([profile()], [profile(city="Астана")], []):
            with self.subTest(rows=rows):
                self.assertEqual(recommend(rows, QUERY)["suggestions"], [])
        absent = recommend([], QUERY)
        self.assertIn("город или категорию", absent["recovery_message"])

    def test_mixed_calendars_count_matches_actual_retry(self):
        rows = [profile("known", busy_dates=[QUERY["date"]], calendar_range=CALENDAR),
                profile("unknown", busy_dates=[QUERY["date"]])]
        self.assert_verified(rows, QUERY, recommend(rows, QUERY)["suggestions"])

    def test_order_is_independent_of_input(self):
        rows = [profile("budget", price_from_kzt=250000),
                profile("hours", max_hours=3)]
        self.assertEqual(recommend(rows, QUERY), recommend(rows[::-1], QUERY))


if __name__ == "__main__":
    unittest.main()
