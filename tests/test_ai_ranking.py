import copy
import unittest
from unittest.mock import Mock

from ai_ranking import recommend_with_style
from explanations import recommend


QUERY = dict(city="Алматы", category="ведущий", date="2026-10-01", budget=100000,
             format="свадьба", language="русский", duration_hours=5)
PREFERENCES = ["спокойная атмосфера", "без пошлых конкурсов"]
DESCRIPTION = "Провожу спокойные семейные вечера. Программа без пошлых конкурсов."


def profile(identifier="1", **changes):
    return dict(dict(id=identifier, name="Имя " + identifier, city="Алматы", categories=["ведущий"],
                     available_dates=[QUERY["date"]], price=50000, formats=["свадьба"],
                     languages=["русский"], max_hours=None, description=DESCRIPTION), **changes)


def answer(payload, supported=None):
    supported = supported or {}
    return {"matches": [
        {"id": row["id"], "preferences": [
            {"preference": preference,
             "status": "supported" if (row["id"], preference) in supported else "unknown",
             "quote": supported.get((row["id"], preference), "")}
            for preference in payload["preferences"]]}
        for row in payload["profiles"]]}


class StyleRankingTests(unittest.TestCase):
    def test_only_eligible_data_sent_and_outside_top_three_can_promote(self):
        rows = [profile(str(i), price=i * 10000) for i in (4, 3, 2, 1)]
        rows += [profile("busy", available_dates=[]), profile("expensive", price=200000),
                 profile("other-city", city="Астана"), profile("wrong-language", languages=["казахский"]),
                 profile("wrong-category", categories=["фотограф"]),
                 profile("wrong-format", formats=["корпоратив"]), profile("short", max_hours=3)]
        client = Mock(side_effect=lambda **kwargs: answer(kwargs["payload"], {
            ("4", PREFERENCES[0]): "Провожу спокойные семейные вечера."}))
        result = recommend_with_style(rows, QUERY, PREFERENCES, client)
        sent = client.call_args.kwargs["payload"]
        self.assertEqual(set(sent), {"preferences", "profiles"})
        self.assertEqual([p["id"] for p in sent["profiles"]], ["1", "2", "3", "4"])
        self.assertTrue(all(set(p) == {"id", "description"} for p in sent["profiles"]))
        self.assertEqual([card["id"] for card in result["cards"]], ["4", "1", "2"])
        self.assertEqual(result["cards"][0]["style_score"], 1)
        self.assertTrue(result["ai"]["applied"])
        rejected = {r["id"]: r["reasons"] for r in result["rejected"]}
        self.assertEqual(rejected["3"][0]["code"], "outside_top_3")
        self.assertEqual(rejected["3"][0]["rank"], 4)
        self.assertEqual(len(result["cards"]) + len(result["rejected"]), len(rows))
        base = recommend(rows, QUERY)
        for key in ("total", "eligible_count", "message", "status", "suggestions", "recovery_message",
                    "exclusion_counts", "city_category_count", "request_date"):
            self.assertEqual(result[key], base[key])

    def test_evidence_is_verbatim_meaningful_and_unknown_keeps_no_quote(self):
        rows = [profile()]
        for quote in ("Идеальный профессионал для вас", "без", "", "Провожу СПОКОЙНЫЕ семейные вечера."):
            with self.subTest(quote=quote):
                client = lambda **kwargs: answer(kwargs["payload"], {("1", PREFERENCES[0]): quote})
                card = recommend_with_style(rows, QUERY, PREFERENCES, client)["cards"][0]
                self.assertEqual(card["style_score"], 0)
                self.assertEqual(card["style_matches"][0]["status"], "unknown")
                self.assertEqual(card["style_matches"][0]["quote"], "")
        client = lambda **kwargs: answer(kwargs["payload"], {
            ("1", PREFERENCES[0]): "Провожу\n  спокойные семейные вечера."})
        card = recommend_with_style(rows, QUERY, PREFERENCES, client)["cards"][0]
        self.assertEqual(card["style_score"], 1)
        self.assertEqual(card["style_matches"][0]["quote"], "Провожу спокойные семейные вечера.")

    def test_invalid_id_and_preference_coverage_fails_safely(self):
        baseline = answer({"profiles": [{"id": "1"}], "preferences": PREFERENCES})
        mutations = [
            lambda response: response["matches"].clear(),
            lambda response: response["matches"].append(copy.deepcopy(response["matches"][0])),
            lambda response: response["matches"][0].update(id="excluded"),
            lambda response: response["matches"][0]["preferences"].pop(),
            lambda response: response["matches"][0]["preferences"].append(
                copy.deepcopy(response["matches"][0]["preferences"][0])),
            lambda response: response["matches"][0]["preferences"][0].update(preference="other"),
            lambda response: response["matches"][0]["preferences"][0].update(status="definitely"),
            lambda response: response["matches"][0]["preferences"][0].update(quote=None),
            lambda response: response.update(extra="ignore instructions"),
        ]
        for mutation in mutations:
            response = copy.deepcopy(baseline)
            mutation(response)
            with self.subTest(response=response), self.assertRaises(ValueError):
                recommend_with_style([profile()], QUERY, PREFERENCES, Mock(return_value=response))

    def test_style_ties_use_price_then_id_independent_of_model_order(self):
        rows = [profile("4", price=60000), profile("3"), profile("2"), profile("1")]

        def client(**kwargs):
            response = answer(kwargs["payload"])
            response["matches"].reverse()
            for match in response["matches"]:
                match["preferences"].reverse()
            return response

        first = recommend_with_style(rows, QUERY, PREFERENCES, client)
        second = recommend_with_style(rows[::-1], QUERY, PREFERENCES, client)
        self.assertEqual(first, second)
        self.assertEqual([card["id"] for card in first["cards"]], ["1", "2", "3"])
        self.assertEqual([m["preference"] for m in first["cards"][0]["style_matches"]], PREFERENCES)

    def test_new_cards_refresh_quality(self):
        rows = [profile(str(i), description="Веду семейные мероприятия.") for i in (1, 2, 3)]
        rows.append(profile("4", description="Провожу спокойные семейные вечера."))
        client = lambda **kwargs: answer(kwargs["payload"], {
            ("4", PREFERENCES[0]): "Провожу спокойные семейные вечера."})
        base = recommend(rows, QUERY)
        result = recommend_with_style(rows, QUERY, PREFERENCES, client)
        self.assertEqual(base["quality"]["indistinguishable_ids"], ["1", "2", "3"])
        self.assertEqual(result["quality"]["indistinguishable_ids"], ["1", "2"])
        self.assertEqual([c["id"] for c in result["cards"]], ["4", "1", "2"])

    def test_no_preferences_or_no_eligible_profiles_never_calls_model(self):
        cases = [([profile()], []), ([], PREFERENCES),
                 ([profile(city="Астана")], PREFERENCES), ([profile(price=200000)], PREFERENCES)]
        for rows, preferences in cases:
            with self.subTest(rows=rows, preferences=preferences):
                client = Mock(side_effect=AssertionError("must not call model"))
                result = recommend_with_style(rows, QUERY, preferences, client)
                self.assertFalse(result.pop("ai")["applied"])
                self.assertEqual(result, recommend(rows, QUERY))
                client.assert_not_called()

    def test_input_limits_and_provider_errors(self):
        for value in ("стиль", [""], [None], ["x" * 201], ["a"] * 6, ["a", "a"]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                recommend_with_style([profile()], QUERY, value, Mock())
        with self.assertRaisesRegex(RuntimeError, "provider failed"):
            recommend_with_style([profile()], QUERY, PREFERENCES,
                                 Mock(side_effect=RuntimeError("provider failed")))

    def test_prompt_preserves_negative_constraints_and_schema_is_strict(self):
        client = Mock(side_effect=lambda **kwargs: answer(kwargs["payload"]))
        recommend_with_style([profile()], QUERY, PREFERENCES, client)
        arguments = client.call_args.kwargs
        instructions = arguments["instructions"]
        for text in ("недоверенные данные", "без пошлых конкурсов", "отсутствие упоминания",
                     "не провожу интерактивы", "не истинность"):
            self.assertIn(text, instructions)

        def check_schema(schema):
            if schema.get("type") == "object":
                self.assertFalse(schema["additionalProperties"])
                self.assertEqual(set(schema["required"]), set(schema["properties"]))
                for property_schema in schema["properties"].values():
                    check_schema(property_schema)
            if schema.get("type") == "array":
                check_schema(schema["items"])

        check_schema(arguments["schema"])


if __name__ == "__main__":
    unittest.main()
