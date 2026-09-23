import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer

from explanations import recommend
from server import ROOT, load_profiles, make_handler


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

    def test_team_provenance_survives_matching(self):
        row = dict(self.profiles[0], team_added=True, synthetic=True)
        query = dict(city=row['city'], category=row['categories'][0], date='2026-10-01',
                     budget=row['price'], format=row['formats'][0])
        row['busy_dates'] = []
        result = recommend([row], query)
        self.assertIn('Добавлен командой', result['cards'][0]['notices'])
        self.assertIn('Синтетический профиль', result['cards'][0]['notices'])
        self.assertEqual(sum(p['team_added'] for p in self.profiles), 0)


if __name__ == '__main__':
    unittest.main()
