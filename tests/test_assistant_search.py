import copy
import unittest
from unittest.mock import Mock

from assistant_search import assistant_recommend
from matching import select_candidates


PREFERENCE = "современные интерактивы"
DESCRIPTION = "Провожу современные интерактивы и музыкальные викторины."


def profile(identifier="1", **changes):
    return dict(dict(id=identifier, name="Имя " + identifier, city="Алматы", categories=["ведущий"],
                     busy_dates=[], calendar_range={"start": "2026-09-23", "end": "2026-12-31"},
                     price=50000, formats=["свадьба"], languages=["русский"], max_hours=None,
                     description=DESCRIPTION), **changes)


def client_for(supported=()):
    def respond(**kwargs):
        payload = kwargs["payload"]
        return {"matches": [
            {"id": row["id"], "preferences": [
                {"preference": preference,
                 "status": "supported" if (row["id"], preference) in supported else "unknown",
                 "quote": DESCRIPTION if (row["id"], preference) in supported else ""}
                for preference in payload["preferences"]]}
            for row in payload["profiles"]]}
    return Mock(side_effect=respond)


class AssistantSearchTests(unittest.TestCase):
    def test_missing_fields_do_not_become_filters_and_no_date_is_not_free(self):
        rows = [profile(price=10_000_000, max_hours=0, languages=[],
                        busy_dates=["2026-10-01"], calendar_range=None)]
        client = Mock(side_effect=AssertionError("No model needed"))
        result = assistant_recommend(rows, {"category": "ведущий"}, [], client)
        client.assert_not_called()
        self.assertEqual(result["eligible_count"], 1)
        self.assertIsNone(result["request_date"])
        self.assertIsNone(result["request"]["budget"])
        self.assertIn("доступность не проверялась", result["cards"][0]["explanation"])
        self.assertNotIn("бюджет", result["cards"][0]["explanation"])

    def test_null_budget_and_real_zero_differ(self):
        rows = [profile()]
        self.assertEqual(assistant_recommend(rows, {"city": "Алматы", "budget": None}, [], None)["eligible_count"], 1)
        result = assistant_recommend(rows, {"budget": 0}, [], None)
        self.assertEqual(result["cards"], [])
        difference = result["alternatives"][0]["differences"][0]
        self.assertEqual((difference["field"], difference["requested"], difference["actual"]), ("budget", 0, 50000))
        self.assertIn("50 000", difference["message"])
        self.assertEqual(assistant_recommend([profile(price=0)], {"budget": 0}, [], None)["eligible_count"], 1)

    def test_empty_request_never_shows_arbitrary_catalog(self):
        result = assistant_recommend([profile()], {"budget": None, "languages": []}, [], None)
        self.assertEqual(result["cards"], [])
        self.assertEqual(result["alternatives"], [])
        self.assertEqual(result["eligible_count"], 0)
        self.assertIn("хотя бы одно", result["message"])

    def test_city_category_always_anchor_alternatives(self):
        rows = [profile("other-city", city="Астана"), profile("other-service", categories=["фотограф"]),
                profile("local", price=150000)]
        client = client_for()
        result = assistant_recommend(rows, {"city": "Алматы", "category": "ведущий", "budget": 100000}, [PREFERENCE], client)
        self.assertEqual([card["id"] for card in result["alternatives"]], ["local"])
        self.assertEqual([p["id"] for p in client.call_args.kwargs["payload"]["profiles"]], ["local"])
        for query in ({"city": "Неизвестный город"}, {"category": "Другое"}):
            with self.subTest(query=query):
                result = assistant_recommend(rows, query, [PREFERENCE], Mock(side_effect=AssertionError()))
                self.assertEqual(result["cards"], [])
                self.assertEqual(result["alternatives"], [])

    def test_every_preference_must_have_evidence_for_exact_match(self):
        rows = [profile("1"), profile("2"), profile("3")]
        client = client_for({("2", PREFERENCE)})
        result = assistant_recommend(rows, {"category": "ведущий"}, [PREFERENCE], client)
        self.assertEqual([card["id"] for card in result["cards"]], ["2"])
        self.assertEqual(result["hard_match_count"], 3)
        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["alternatives"], [])
        self.assertTrue(result["ai"]["applied"])
        client.assert_called_once()
        for rejected in result["rejected"]:
            self.assertEqual(rejected["reasons"][0]["code"], "preference_unconfirmed")

    def test_one_missing_preference_prevents_exact_match(self):
        result = assistant_recommend([profile()], {}, [PREFERENCE, "тихая атмосфера"],
                                     client_for({("1", PREFERENCE)}))
        self.assertEqual(result["cards"], [])
        card = result["alternatives"][0]
        self.assertEqual(card["style_score"], 1)
        self.assertEqual(card["differences"][0]["requested"], "тихая атмосфера")
        self.assertEqual(card["style_matches"][1]["quote"], "")

    def test_invented_quote_is_never_exact(self):
        client = client_for({("1", PREFERENCE)})
        result = assistant_recommend([profile(description="Другие услуги по договорённости.")],
                                     {}, [PREFERENCE], client)
        self.assertEqual(result["cards"], [])
        self.assertEqual(result["alternatives"][0]["style_score"], 0)

    def test_date_alternative_is_nearest_known_free_and_prefers_future(self):
        rows = [profile(busy_dates=["2026-10-01"])]
        query = {"category": "ведущий", "date": "2026-10-01"}
        result = assistant_recommend(rows, query, [], None)
        self.assertEqual(result["cards"], [])
        card = result["alternatives"][0]
        self.assertEqual(card["proposed_date"], "2026-10-02")
        self.assertEqual(card["differences"][0]["requested"], "2026-10-01")
        self.assertEqual(result["request_date"], "2026-10-01")
        self.assertEqual(query["date"], "2026-10-01")

    def test_date_search_reaches_beyond_one_week_and_handles_calendar_bounds(self):
        rows = [profile(available_dates=["2026-11-01", "2026-12-20"])]
        result = assistant_recommend(rows, {"date": "2026-10-01"}, [], None)
        self.assertEqual(result["alternatives"][0]["proposed_date"], "2026-11-01")
        rows = [profile(busy_dates=["2026-12-31"])]
        result = assistant_recommend(rows, {"date": "2027-01-05"}, [], None)
        self.assertEqual(result["alternatives"][0]["proposed_date"], "2026-12-30")

    def test_busy_and_calendar_overrule_available_list(self):
        rows = [profile(available_dates=["2026-10-01", "2026-10-02", "2027-01-01"],
                        busy_dates=["2026-10-01", "2026-10-02"])]
        result = assistant_recommend(rows, {"date": "2026-10-01"}, [], None)
        self.assertIsNone(result["alternatives"][0]["proposed_date"])
        self.assertIn("Свободная дата не подтверждена", result["alternatives"][0]["differences"][0]["message"])

    def test_unknown_calendar_never_claims_available(self):
        result = assistant_recommend([profile(calendar_range=None)], {"date": "2026-10-01"}, [], None)
        self.assertEqual(result["cards"], [])
        self.assertIsNone(result["alternatives"][0]["proposed_date"])
        self.assertIn("нет данных календаря", result["alternatives"][0]["differences"][0]["message"])

    def test_multiple_differences_all_disclosed(self):
        rows = [profile(price=150000, max_hours=3, languages=["английский"], formats=["концерт"],
                        busy_dates=["2026-10-01"])]
        request = {"date": "2026-10-01", "budget": 100000, "duration_hours": 5,
                   "languages": ["русский", "казахский"], "format": "свадьба"}
        result = assistant_recommend(rows, request, [PREFERENCE], client_for())
        card = result["alternatives"][0]
        self.assertEqual([d["field"] for d in card["differences"]],
                         ["date", "budget", "format", "languages", "duration_hours", "preferences"])
        self.assertTrue(all(d["message"] for d in card["differences"]))
        self.assertEqual(card["proposed_date"], "2026-10-02")
        self.assertNotIn("не превышает бюджет", card["explanation"])

    def test_alternatives_rank_fewer_changed_conditions_then_distance_and_budget(self):
        rows = [profile("two", price=110000, max_hours=3), profile("one", price=130000),
                profile("far-date", available_dates=["2026-10-20"]),
                profile("near-date", available_dates=["2026-10-02"])]
        query = {"date": "2026-10-01", "budget": 100000, "duration_hours": 5}
        result = assistant_recommend(rows, query, [], None)
        self.assertEqual([card["id"] for card in result["alternatives"]], ["one", "near-date", "far-date"])
        rows = [profile("two", price=110000, max_hours=3), profile("three", price=101000, max_hours=3, languages=[])]
        query["language"] = "русский"
        result = assistant_recommend(rows, query, [], None)
        self.assertEqual(result["alternatives"][0]["id"], "two")

    def test_top_three_and_ties_are_stable(self):
        rows = [profile(str(i)) for i in [4, 3, 2, 1]]
        first = assistant_recommend(rows, {"city": "Алматы"}, [], None)
        second = assistant_recommend(rows[::-1], {"city": "Алматы"}, [], None)
        self.assertEqual(first, second)
        self.assertEqual([card["id"] for card in first["cards"]], ["1", "2", "3"])
        self.assertEqual(first["eligible_count"], 4)
        self.assertEqual(first["rejected"][0]["reasons"][0]["code"], "outside_top_3")
        first = assistant_recommend(rows, {"budget": 0}, [], None)
        second = assistant_recommend(rows[::-1], {"budget": 0}, [], None)
        self.assertEqual(first, second)
        self.assertEqual([card["id"] for card in first["alternatives"]], ["1", "2", "3"])

    def test_provider_failure_and_invalid_reply_never_ignore_preferences(self):
        for client in (Mock(side_effect=RuntimeError("secret-provider-error")), Mock(return_value={"matches": []})):
            result = assistant_recommend([profile()], {"city": "Алматы"}, [PREFERENCE], client)
            self.assertEqual(result["cards"], [])
            self.assertFalse(result["ai"]["applied"])
            self.assertEqual(result["alternatives"][0]["differences"][0]["field"], "preferences")
            self.assertNotIn("secret-provider-error", str(result))
            client.assert_called_once()

    def test_input_immutable_and_all_anchor_profiles_scored_in_one_call(self):
        rows = [profile("eligible"), profile("expensive", price=500000),
                profile("busy", busy_dates=["2026-10-01"])]
        query = {"city": "Алматы", "category": "ведущий", "budget": 100000, "date": "2026-10-01"}
        original = copy.deepcopy((rows, query))
        client = client_for()
        assistant_recommend(rows, query, [PREFERENCE], client)
        self.assertEqual((rows, query), original)
        client.assert_called_once()
        self.assertEqual(len(client.call_args.kwargs["payload"]["profiles"]), 3)
        self.assertTrue(all(set(row) == {"id", "description"} for row in client.call_args.kwargs["payload"]["profiles"]))

    def test_matching_partial_opt_in_and_unlimited_pool(self):
        rows = [profile(str(i)) for i in range(5)]
        result = select_candidates(rows, {"city": "Алматы"}, partial=True, limit=None)
        self.assertEqual(len(result["candidates"]), 5)
        self.assertEqual(result["rejected"], [])
        self.assertEqual(result["candidates"][0]["facts"]["availability_basis"], "not_checked")
        with self.assertRaises(KeyError):
            select_candidates(rows, {"city": "Алматы"})


if __name__ == "__main__":
    unittest.main()
