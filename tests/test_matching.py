import unittest
from matching import compare_sources, normalize_profiles, select_candidates


def profile(identifier="1", **changes):
    return dict(dict(id=identifier, name="Тест", city="Алматы", categories=["ведущий"],
                     available_dates=["2026-10-01"], price=50000, formats=["офлайн"],
                     languages=["русский"], max_hours=None), **changes)


QUERY = dict(city="Алматы", category="ведущий", date="2026-10-01", budget=100000,
             format="офлайн", language="русский", duration_hours=5)


class MatchingTests(unittest.TestCase):
    def test_actual_columns(self):
        row = dict(id="HK-demo", anon_name="Демо", city="Алматы", categories="Ведущий|Фотограф",
                   price_from_kzt="50 000", event_formats="свадьба|той", languages="русский|казахский",
                   max_hours="", busy_dates="2026-09-25|2026-09-26", city_imputed="FALSE",
                   price_imputed="TRUE", synthetic="FALSE", description="Описание")
        normalized = normalize_profiles([row])
        self.assertEqual(normalized, normalize_profiles(normalized))
        self.assertEqual(normalized[0]["categories"], ["ведущий", "фотограф"])
        self.assertFalse(normalized[0]["synthetic"])
        self.assertTrue(normalized[0]["price_imputed"])
        query = dict(QUERY, format="свадьба", date="2026-09-25")
        self.assertEqual(select_candidates([row], query)["rejected"][0]["reasons"][0]["code"], "date_busy")
        result = select_candidates([row], dict(query, date="2026-09-27"))
        facts = result["candidates"][0]["facts"]
        self.assertTrue(facts["price_requires_confirmation"])
        self.assertEqual(facts["availability_basis"], "not_in_busy_dates")
        self.assertEqual(normalized[0]["description"], "Описание")

    def test_empty_busy_dates_and_conflicting_availability(self):
        row = profile(busy_dates="", available_dates=None)
        self.assertEqual(len(select_candidates([row], QUERY)["candidates"]), 1)
        row = profile(busy_dates=[QUERY["date"]])
        self.assertEqual(select_candidates([row], QUERY)["candidates"], [])

    def test_normalization_and_equivalence(self):
        raw = profile(price="50 000,00", categories="ВЕДУЩИЙ", available_dates="01.10.2026",
                      formats='["Офлайн"]', languages="Русский", city=" Алматы ")
        self.assertTrue(compare_sources([raw], [profile()])["equivalent"])

    def test_conflicts_and_distinct_ids(self):
        result = compare_sources([profile(), profile("2")], [profile(price=1), profile("3")])
        self.assertFalse(result["equivalent"])
        self.assertEqual(result["only_excel"], ["2"])
        self.assertEqual(result["only_html"], ["3"])
        self.assertEqual(result["conflicts"][0]["fields"]["price"]["html"], 1)

    def test_null_hours_unlimited(self):
        result = select_candidates([profile()], dict(QUERY, duration_hours=100))
        self.assertEqual(len(result["candidates"]), 1)

    def test_every_filter(self):
        changes = [("city", "Астана", "city_mismatch"),
                   ("categories", ["фотограф"], "category_mismatch"),
                   ("available_dates", [], "date_unavailable"),
                   ("price", 100001, "over_budget"),
                   ("formats", ["онлайн"], "format_mismatch"),
                   ("languages", ["казахский"], "language_mismatch"),
                   ("max_hours", 4, "duration_exceeded")]
        for field, value, code in changes:
            with self.subTest(field=field):
                result = select_candidates([profile(**{field: value})], QUERY)
                self.assertEqual(result["candidates"], [])
                self.assertEqual(result["rejected"][0]["reasons"][0]["code"], code)

    def test_top_three_and_stable_ties(self):
        rows = [profile(str(i)) for i in [4, 2, 3, 1]]
        result = select_candidates(rows, QUERY)
        self.assertEqual(result, select_candidates(rows[::-1], QUERY))
        self.assertEqual([p["profile"]["id"] for p in result["candidates"]], ["1", "2", "3"])
        self.assertEqual(result["rejected"][0]["reasons"][0]["code"], "outside_top_3")

    def test_budget_ranking_and_boundaries(self):
        result = select_candidates([profile("a", price=100000, max_hours=5), profile("b", price=1)], QUERY)
        self.assertEqual([p["profile"]["id"] for p in result["candidates"]], ["b", "a"])
        self.assertEqual(select_candidates([profile(price=0)], dict(QUERY, budget=0))["candidates"][0]["score"], 100)

    def test_optional_filters(self):
        query = {k: v for k, v in QUERY.items() if k not in ("language", "duration_hours")}
        self.assertEqual(len(select_candidates([profile(languages=[], max_hours=0)], query)["candidates"]), 1)

    def test_invalid_data(self):
        for value in (None, True, -1, "NaN", "Infinity"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_profiles([profile(price=value)])
        with self.assertRaises(ValueError):
            normalize_profiles([profile(), profile()])
        with self.assertRaises(ValueError):
            normalize_profiles([profile(available_dates=["31.02.2026"])])


if __name__ == "__main__":
    unittest.main()
