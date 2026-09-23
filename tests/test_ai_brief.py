import copy
import unittest

from ai_brief import parse_brief
from ai_client import AIError
from matching import select_candidates
from test_matching import QUERY, profile


class BriefTests(unittest.TestCase):
    def setUp(self):
        self.rows = [profile(languages=['русский', 'казахский'])]
        self.output = {'request': {'city': 'Алматы', 'category': 'ведущий', 'date': '2026-10-01',
                                  'budget': 800000, 'format': 'офлайн', 'duration_hours': 5,
                                  'languages': ['русский', 'казахский']},
                       'preferences': ['без пошлых конкурсов'], 'questions': [], 'warnings': []}
        # Use the normalized catalogue as the service does.
        from matching import normalize_profiles
        self.rows = normalize_profiles(self.rows)

    def call(self):
        return parse_brief(self.rows, 'Текст запроса', lambda **kwargs: copy.deepcopy(self.output))

    def test_complete_request_and_multiple_languages(self):
        response = self.call()
        self.assertTrue(response['ready'])
        self.assertEqual(response['request']['languages'], ['русский', 'казахский'])
        self.assertEqual(response['preferences'], ['без пошлых конкурсов'])
        one_language = profile(languages=['русский'])
        result = select_candidates([one_language], response['request'])
        self.assertFalse(result['candidates'])
        self.assertEqual(result['rejected'][0]['reasons'][0]['code'], 'language_mismatch')
        self.assertTrue(select_candidates(self.rows, response['request'])['candidates'])

    def test_missing_fields_never_get_defaults(self):
        self.output['request'].update(date=None, budget=None)
        response = self.call()
        self.assertIsNone(response['request']['date'])
        self.assertIsNone(response['request']['budget'])
        self.assertFalse(response['ready'])
        self.assertEqual(len(response['questions']), 2)

    def test_unsupported_catalogue_value_needs_clarification(self):
        self.output['request']['city'] = 'Неизвестный город'
        result = self.call()
        self.assertIsNone(result['request']['city'])
        self.assertFalse(result['ready'])
        self.assertTrue(result['warnings'])

    def test_model_questions_block_ready_even_with_fields(self):
        self.output['questions'] = ['Какой год?']
        self.assertFalse(self.call()['ready'])

    def test_bad_model_output_is_not_applied(self):
        for field, value in [('date', '2026-02-30'), ('budget', -1), ('budget', True), ('budget', float('nan'))]:
            with self.subTest(field=field, value=value):
                raw = copy.deepcopy(self.output)
                raw['request'][field] = value
                with self.assertRaises(AIError):
                    parse_brief(self.rows, 'Запрос', lambda **kwargs: raw)

    def test_empty_text_does_not_call_provider(self):
        for text in ('', ' ', None, 'я' * 4001):
            with self.subTest(text_type=type(text)), self.assertRaises(ValueError):
                parse_brief(self.rows, text, lambda **kwargs: self.fail('provider called'))

    def test_recovery_removes_all_language_requirements_together(self):
        from explanations import recommend
        query = dict(QUERY, language=None, languages=['русский', 'казахский'])
        result = recommend([profile(languages=['русский'])], query)
        suggestion = next(s for s in result['suggestions'] if s['field'] == 'languages')
        self.assertEqual(suggestion['request']['languages'], [])
        self.assertTrue(select_candidates([profile(languages=['русский'])], suggestion['request'])['candidates'])
        legacy = recommend([profile(languages=['русский'])], dict(query, language='русский'))
        suggestion = next(s for s in legacy['suggestions'] if s['field'] == 'languages')
        self.assertIsNone(suggestion['request']['language'])
        self.assertEqual(suggestion['request']['languages'], [])


if __name__ == '__main__':
    unittest.main()
