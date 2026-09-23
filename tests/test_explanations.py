import json
from pathlib import Path
import unittest

from explanations import recommend
from matching import select_candidates


QUERY = dict(city="Алматы", category="ведущий", date="2026-10-01",
             budget=220000, format="корпоратив", language="русский", duration_hours=5)


def profile(identifier="1", **changes):
    return dict(dict(id=identifier, anon_name="Имя " + identifier, city="Алматы",
                     categories=["ведущий"], busy_dates=[], price_from_kzt=180000,
                     event_formats=["корпоратив"], languages=["русский", "казахский"],
                     max_hours=6, description="Опыт интерактивных программ."), **changes)


class ExplanationTests(unittest.TestCase):
    def test_card_facts_and_price_caveat(self):
        card = recommend([profile()], QUERY)["cards"][0]
        text = card["explanation"]
        for fact in ("от 180 000 ₸", "220 000 ₸", "стоимость нужно уточнить",
                     "корпоратив", "казахский", "русский", "до 6 ч", "5 ч",
                     "2026-10-01", "Опыт интерактивных программ"):
            self.assertIn(fact, text)
        self.assertNotIn("свободен", text)

    def test_three_states(self):
        self.assertEqual(recommend([profile()], QUERY)["status"], "matched")
        absent = recommend([profile(city="Астана")], QUERY)
        blocked = recommend([profile(busy_dates=[QUERY["date"]])], QUERY)
        self.assertEqual(absent["status"], "category_absent")
        self.assertEqual(blocked["status"], "no_matches")
        self.assertIn("заняты", blocked["message"])
        self.assertTrue(absent["message"])

    def test_counts_partition_local_pool(self):
        rows = [profile(str(i), busy_dates=[QUERY["date"]], price_from_kzt=999999)
                for i in range(5)]
        rows += [profile("5", price_from_kzt=999999), profile("6"), profile("7"),
                 profile("other", city="Астана")]
        result = recommend(rows, QUERY)
        self.assertEqual(result["city_category_count"], 8)
        self.assertEqual(result["exclusion_counts"], {"date_busy": 5, "over_budget": 1})
        self.assertEqual(len(result["cards"]), 2)
        self.assertIn("Подходят: 2", result["message"])

    def test_null_hours_and_provenance(self):
        card = recommend([profile(max_hours=None, synthetic=True, price_imputed=True,
                                  city_imputed=True)], QUERY)["cards"][0]
        self.assertIn("не привязана к часам присутствия", card["explanation"])
        self.assertNotIn("безлимит", card["explanation"])
        self.assertEqual(len(card["notices"]), 3)

    def test_only_name_is_not_a_distinction(self):
        rows = [profile("1", description="Имя 1 проводит интерактивные программы."),
                profile("2", description="Имя 2 проводит интерактивные программы.")]
        result = recommend(rows, QUERY)
        self.assertFalse(result["quality"]["distinct_explanations"])
        self.assertEqual(result["quality"]["indistinguishable_ids"], ["1", "2"])
        rows[1]["description"] = "Проводит музыкальные викторины."
        self.assertTrue(recommend(rows, QUERY)["quality"]["distinct_explanations"])

    def test_no_description_does_not_invent_one(self):
        card = recommend([profile(description="")], QUERY)["cards"][0]
        self.assertIsNone(card["description_excerpt"])
        self.assertNotIn("описания", card["explanation"])

    def test_greeting_is_skipped_for_concrete_detail(self):
        row = profile(description="Здравствуйте, друзья! Разрабатываем сценарии музыкальных викторин.")
        card = recommend([row], QUERY)["cards"][0]
        self.assertEqual(card["description_excerpt"], "Разрабатываем сценарии музыкальных викторин.")
        self.assertNotIn("Здравствуйте", card["explanation"])

    def test_order_unchanged_and_date_changes(self):
        rows = [profile(str(i), price_from_kzt=10000 * i) for i in (4, 3, 2, 1)]
        rows[-1]["busy_dates"] = ["2026-10-02"]
        first = recommend(rows, QUERY)
        self.assertEqual(first, recommend(rows[::-1], QUERY))
        self.assertEqual(first["candidates"], select_candidates(rows, QUERY)["candidates"])
        self.assertEqual(first["city_category_count"], 4)
        self.assertNotIn("outside_top_3", first["exclusion_counts"])
        other = recommend(rows, dict(QUERY, date="2026-10-02"))
        self.assertEqual([c["id"] for c in first["cards"]], ["1", "2", "3"])
        self.assertEqual([c["id"] for c in other["cards"]], ["2", "3", "4"])
        self.assertIn("1 — заняты", other["message"])

    def test_all_failure_reasons(self):
        variants = [(dict(calendar_range={"start": "2026-11-01", "end": "2026-12-31"}), "date_outside_calendar"),
                    (dict(available_dates=[]), "date_unavailable"),
                    (dict(event_formats=["свадьба"]), "format_mismatch"),
                    (dict(languages=["английский"]), "language_mismatch"),
                    (dict(max_hours=4), "duration_exceeded")]
        for changes, code in variants:
            with self.subTest(code=code):
                result = recommend([profile(**changes)], QUERY)
                self.assertEqual(result["status"], "no_matches")
                self.assertEqual(result["exclusion_counts"], {code: 1})

    def test_dataset_demo_contract(self):
        root = Path(__file__).resolve().parents[1]
        rows = json.loads((root / "data/profiles.json").read_text(encoding="utf-8"))
        cases = json.loads((root / "examples/quality_requests.json").read_text(encoding="utf-8"))
        results = {}
        for case in cases:
            with self.subTest(case=case["id"]):
                r = recommend(rows, case["request"])
                results[case["id"]] = r
                self.assertEqual(r["status"], case["expected_status"])
                self.assertEqual([c["id"] for c in r["cards"]], case["expected_ids"])
                self.assertEqual(r, recommend(rows[::-1], case["request"]))
                self.assertTrue(r["quality"]["distinct_explanations"])
                self.assertEqual(r["city_category_count"], r["eligible_count"] + sum(r["exclusion_counts"].values()))
                for item in r["candidates"]:
                    self.assertNotIn(case["request"]["date"], item["profile"]["busy_dates"])
        self.assertGreater(results["dense"]["eligible_count"], 3)
        self.assertNotEqual(results["dense"]["cards"], results["other_date"]["cards"])
        first_ids = {c["id"] for c in results["dense"]["cards"]}
        blocked_ids = {r["id"] for r in results["other_date"]["rejected"]
                       if any(reason["code"] == "date_busy" for reason in r["reasons"])}
        self.assertTrue(first_ids & blocked_ids)


if __name__ == "__main__":
    unittest.main()
