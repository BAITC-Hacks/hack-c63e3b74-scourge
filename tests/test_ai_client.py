import io
import json
import tempfile
import unittest
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import ai_client


class ClientTests(unittest.TestCase):
    def call(self):
        return ai_client.complete_json(name='test', schema={'type': 'object'}, instructions='Extract', payload={'text': 'example'})

    def test_unconfigured_does_not_use_network(self):
        with patch('ai_client.settings', return_value=('', 'gpt-4.1-mini')), patch('ai_client.urlopen') as send:
            with self.assertRaises(ai_client.AIError) as caught:
                self.call()
            self.assertEqual(caught.exception.status, 503)
            send.assert_not_called()

    def test_structured_request_and_response(self):
        output = {'status': 'completed', 'output': [{'type': 'message', 'content': [
            {'type': 'output_text', 'text': '{"field": "value"}'}]}]}
        with patch('ai_client.settings', return_value=('test-key', 'gpt-4.1-mini')), \
             patch('ai_client.urlopen', return_value=io.BytesIO(json.dumps(output).encode())) as send:
            self.assertEqual(self.call(), {'field': 'value'})
            request = send.call_args.args[0]
            body = json.loads(request.data)
            self.assertFalse(body['store'])
            self.assertTrue(body['text']['format']['strict'])
            self.assertEqual(request.full_url, 'https://api.openai.com/v1/responses')
            self.assertNotIn('test-key', json.dumps(body))

    def test_provider_errors_are_redacted(self):
        errors = [HTTPError('https://api.openai.com', 401, 'secret-key', {}, None),
                  HTTPError('https://api.openai.com', 429, 'secret-key', {}, None), URLError('secret-key'),
                  ValueError('Invalid header value: secret-key'), IncompleteRead(b'secret-key')]
        for error in errors:
            with self.subTest(error=type(error)), patch('ai_client.settings', return_value=('test', 'gpt-4.1-mini')), \
                 patch('ai_client.urlopen', side_effect=error):
                with self.assertRaises(ai_client.AIError) as caught:
                    self.call()
                self.assertNotIn('secret-key', str(caught.exception))

    def test_invalid_key_cannot_leak_through_headers(self):
        with patch('ai_client.settings', return_value=('secret-key\ninvalid', 'gpt-4.1-mini')), \
             patch('ai_client.urlopen') as send:
            with self.assertRaises(ai_client.AIError) as caught:
                self.call()
            self.assertNotIn('secret-key', str(caught.exception))
            send.assert_not_called()

    def test_incomplete_and_refusal_fail_safely(self):
        for output in ({'status': 'incomplete'}, {'status': 'completed', 'output': []},
                       {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'refusal'}]}]}):
            with patch('ai_client.settings', return_value=('test', 'gpt-4.1-mini')), \
                 patch('ai_client.urlopen', return_value=io.BytesIO(json.dumps(output).encode())):
                with self.assertRaises(ai_client.AIError):
                    self.call()

    def test_dotenv_no_execution_and_env_precedence(self):
        with tempfile.TemporaryDirectory() as tmp, patch('ai_client.ROOT', Path(tmp)), \
             patch.dict('os.environ', {}, clear=True):
            (Path(tmp) / '.env').write_text('OPENAI_API_KEY="local-test"\nOPENAI_MODEL=gpt-4.1-mini\nEVIL=$(touch x)\n')
            self.assertEqual(ai_client.settings(), ('local-test', 'gpt-4.1-mini'))
            self.assertNotIn('local-test', str(ai_client.public_status()))
            with patch.dict('os.environ', {'OPENAI_API_KEY': 'env-test'}):
                self.assertEqual(ai_client.settings()[0], 'env-test')


if __name__ == '__main__':
    unittest.main()
