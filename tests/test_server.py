import http.client
import json
import threading
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from explanations import recommend
from server import ROOT, load_profiles, make_handler
from ai_client import AIError


class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profiles = load_profiles()
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(cls.profiles))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        if isinstance(body, str):
            body = body.encode('utf-8')
        conn.request(method, path, body, {'Content-Type': 'application/json'})
        response = conn.getresponse()
        status, headers, content = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return status, headers, content

    def test_assets_and_private_paths(self):
        for path in ('/', '/app.js', '/style.css', '/api/meta'):
            status, headers, content = self.request('GET', path)
            self.assertEqual(status, 200)
            self.assertIn('Content-Security-Policy', headers)
            self.assertTrue(content)
        for path in ('/../server.py', '/data/profiles.json', '/.env'):
            self.assertEqual(self.request('GET', path)[0], 404)

    def test_all_demo_requests_over_http(self):
        cases = json.loads((ROOT / 'examples/quality_requests.json').read_text())
        for case in cases:
            with self.subTest(case=case['id']):
                status, _, body = self.request('POST', '/api/recommend', json.dumps(case['request']))
                self.assertEqual(status, 200)
                result = json.loads(body)
                self.assertEqual([c['id'] for c in result['cards']], case['expected_ids'])
                self.assertEqual(result['status'], case['expected_status'])

    def test_bad_requests(self):
        for body in ('[]', '{}', '{broken', '{"city": null}'):
            self.assertEqual(self.request('POST', '/api/recommend', body)[0], 400)
        self.assertEqual(self.request('POST', '/api/recommend', ' ' * 16385)[0], 413)

    def test_comparison_over_http(self):
        query = json.loads((ROOT / 'examples/quality_requests.json').read_text())[0]['request']
        status, _, body = self.request('POST', '/api/compare', json.dumps(dict(query, compare_date='2026-10-01')))
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertEqual([r['request_date'] for r in result['results']], ['2026-10-06', '2026-10-01'])
        self.assertEqual(result['changes'][0]['id'], 'HK-35215')
        self.assertIn('date_busy', result['changes'][0]['states'][1]['codes'])
        for value in (None, '', '2026-02-30', 20261001):
            with self.subTest(value=value):
                status, _, _ = self.request('POST', '/api/compare', json.dumps(dict(query, compare_date=value)))
                self.assertEqual(status, 400)

    def test_recovery_can_be_applied_over_http(self):
        cases = json.loads((ROOT / 'examples/quality_requests.json').read_text())
        query = next(case['request'] for case in cases if case['id'] == 'no_matches')
        _, _, body = self.request('POST', '/api/recommend', json.dumps(query))
        suggestion = json.loads(body)['suggestions'][0]
        self.assertEqual(suggestion['field'], 'budget')
        status, _, body = self.request('POST', '/api/recommend', json.dumps(suggestion['request']))
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertEqual(result['status'], 'matched')
        self.assertEqual(result['eligible_count'], suggestion['eligible_count'])

    def test_team_provenance_survives_matching(self):
        row = dict(self.profiles[0], team_added=True, synthetic=True)
        query = dict(city=row['city'], category=row['categories'][0], date='2026-10-01',
                     budget=row['price'], format=row['formats'][0])
        row['busy_dates'] = []
        result = recommend([row], query)
        self.assertIn('Добавлен командой', result['cards'][0]['notices'])
        self.assertIn('Синтетический профиль', result['cards'][0]['notices'])
        self.assertEqual(sum(p['team_added'] for p in self.profiles), 0)

    def test_ai_parse_over_http(self):
        extracted = {'request': {'city': 'алматы', 'category': 'ведущий', 'date': None,
                                'budget': None, 'format': 'свадьба', 'languages': ['русский', 'казахский'],
                                'duration_hours': None},
                     'preferences': ['без пошлых конкурсов'], 'questions': [], 'warnings': []}
        with patch('server.complete_json', return_value=extracted):
            status, _, body = self.request('POST', '/api/ai/parse', json.dumps({'text': 'Описание события'}))
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertFalse(result['ready'])
        self.assertIsNone(result['request']['date'])
        self.assertEqual(result['request']['languages'], ['русский', 'казахский'])
        with patch('server.complete_json', side_effect=AIError('AI не подключён', 503)):
            self.assertEqual(self.request('POST', '/api/ai/parse', '{"text":"Описание"}')[0], 503)

    def test_ai_ranking_http_and_explicit_fallback(self):
        query = json.loads((ROOT / 'examples/quality_requests.json').read_text())[0]['request']
        query['preferences'] = ['спокойная атмосфера']

        def unknown(**kwargs):
            return {'matches': [{'id': p['id'], 'preferences': [
                {'preference': pref, 'status': 'unknown', 'quote': ''}
                for pref in kwargs['payload']['preferences']]} for p in kwargs['payload']['profiles']]}

        with patch('server.complete_json', side_effect=unknown):
            status, _, body = self.request('POST', '/api/ai/recommend', json.dumps(query))
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertTrue(result['ai']['applied'])
        self.assertTrue(all(c['style_matches'][0]['status'] == 'unknown' for c in result['cards']))
        with patch('server.complete_json', side_effect=AIError('Не удалось связаться с OpenAI')):
            status, _, body = self.request('POST', '/api/ai/recommend', json.dumps(query))
        self.assertEqual(status, 200)
        fallback = json.loads(body)
        self.assertFalse(fallback['ai']['applied'])
        self.assertEqual(fallback['cards'], recommend(self.profiles, query)['cards'])
        self.assertIn('не оценены', fallback['ai']['message'])

    def test_ai_invalid_input_never_calls_model(self):
        with patch('server.complete_json') as model:
            for text in (None, '', 'x' * 4001):
                self.assertEqual(self.request('POST', '/api/ai/parse', json.dumps({'text': text}))[0], 400)
            query = json.loads((ROOT / 'examples/quality_requests.json').read_text())[0]['request']
            query['preferences'] = ['x'] * 6
            self.assertEqual(self.request('POST', '/api/ai/recommend', json.dumps(query))[0], 400)
            model.assert_not_called()

    def test_text_search_ignores_other_payload_fields_and_autosearches(self):
        raw = {'request': {'city': 'алматы', 'category': 'ведущий', 'date': None,
                           'budget': None, 'format': None, 'languages': [], 'duration_hours': None},
               'preferences': [], 'questions': [], 'warnings': []}
        payload = {'text': 'Нужен ведущий в Алматы', 'budget': 0, 'date': '1900-01-01',
                   'city': 'Астана', 'language': 'несуществующий'}
        with patch('server.complete_json', return_value=raw) as model:
            status, _, body = self.request('POST', '/api/ai/search', json.dumps(payload))
        self.assertEqual(status, 200)
        response = json.loads(body)
        self.assertTrue(response['parsed']['ready'])
        self.assertTrue(response['result']['cards'])
        self.assertIsNone(response['result']['request_date'])
        self.assertTrue(all(c['city'] == 'алматы' for c in response['result']['cards']))
        model.assert_called_once()
        self.assertEqual(model.call_args.kwargs['payload']['description'], payload['text'])
        self.assertNotIn('1900-01-01', str(model.call_args.kwargs['payload']))

    def test_text_search_asks_only_for_ambiguity(self):
        raw = {'request': {'city': 'алматы', 'category': 'ведущий', 'date': None,
                           'budget': None, 'format': None, 'languages': [], 'duration_hours': None},
               'preferences': [], 'questions': ['Какой год?'], 'warnings': []}
        with patch('server.complete_json', return_value=raw), patch('server.assistant_recommend') as search:
            status, _, body = self.request('POST', '/api/ai/search', '{"text":"Ведущий 10 октября"}')
        self.assertEqual(status, 200)
        self.assertIsNone(json.loads(body)['result'])
        search.assert_not_called()

    def test_text_search_returns_labeled_alternatives(self):
        raw = {'request': {'city': 'алматы', 'category': 'ведущий', 'date': '2026-10-06',
                           'budget': 0, 'format': 'свадьба', 'languages': [], 'duration_hours': None},
               'preferences': [], 'questions': [], 'warnings': []}
        with patch('server.complete_json', return_value=raw):
            status, _, body = self.request('POST', '/api/ai/search', '{"text":"Ведущий бесплатно в Алматы"}')
        self.assertEqual(status, 200)
        result = json.loads(body)['result']
        self.assertEqual(result['cards'], [])
        self.assertTrue(result['alternatives'])
        self.assertTrue(all(any(d['field'] == 'budget' for d in c['differences']) for c in result['alternatives']))


if __name__ == '__main__':
    unittest.main()
