"""Minimal server-only OpenAI Responses client; never exposes provider errors or keys."""
import json
import os
import socket
import threading
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
_SLOTS = threading.BoundedSemaphore(2)


class AIError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def settings():
    """Read only our two keys, no shell evaluation; environment takes precedence."""
    values = {}
    path = ROOT / '.env'
    if path.is_file():
        for line in path.read_text(encoding='utf-8').splitlines():
            key, sep, value = line.strip().removeprefix('export ').partition('=')
            key, value = key.strip(), value.strip()
            if sep and key in ('OPENAI_API_KEY', 'OPENAI_MODEL'):
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                values[key] = value
    api_key = os.environ.get('OPENAI_API_KEY', values.get('OPENAI_API_KEY', '')).strip()
    model = os.environ.get('OPENAI_MODEL', values.get('OPENAI_MODEL', 'gpt-4.1-mini')).strip()
    return api_key, model or 'gpt-4.1-mini'


def public_status():
    api_key, model = settings()
    return {'configured': bool(api_key), 'model': model}


def complete_json(*, name, schema, instructions, payload):
    api_key, model = settings()
    if not api_key:
        raise AIError('AI пока не подключён. Настройте OPENAI_API_KEY на сервере; обычный подбор доступен.', 503)
    if not api_key.isascii() or any(char.isspace() or not char.isprintable() for char in api_key):
        raise AIError('Некорректный формат OPENAI_API_KEY на сервере.', 503)
    if not _SLOTS.acquire(blocking=False):
        raise AIError('AI обрабатывает другие запросы. Повторите немного позже.', 429)
    try:
        body = {'model': model, 'store': False, 'instructions': instructions,
                'input': json.dumps(payload, ensure_ascii=False, allow_nan=False),
                'max_output_tokens': 12000 if name == 'style_matches' else 2200,
                'text': {'format': {'type': 'json_schema', 'name': name,
                                    'schema': schema, 'strict': True}}}
        if model.startswith('gpt-4.1'):
            body['temperature'] = 0
        request = Request('https://api.openai.com/v1/responses',
                          data=json.dumps(body, ensure_ascii=False, allow_nan=False).encode(),
                          headers={'Authorization': 'Bearer ' + api_key, 'Content-Type': 'application/json'},
                          method='POST')
        try:
            with urlopen(request, timeout=45) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise AIError('Ответ AI слишком большой. Сократите пожелания.')
        except HTTPError as exc:
            # Do not send raw provider bodies, request headers or credentials to the UI.
            exc.close()
            if exc.code in (401, 403):
                raise AIError('OpenAI отклонил доступ. Проверьте ключ и доступ к модели на сервере.', 503) from None
            if exc.code == 429:
                raise AIError('Достигнут лимит OpenAI. Попробуйте позже или проверьте баланс API.', 503) from None
            raise AIError('OpenAI временно не выполнил запрос. Обычный подбор доступен.') from None
        except (URLError, TimeoutError, socket.timeout, OSError, HTTPException, ValueError):
            raise AIError('Не удалось связаться с OpenAI за отведённое время. Обычный подбор доступен.', 503) from None
        try:
            result = json.loads(raw)
            if result.get('status') != 'completed':
                raise AIError('AI не завершил ответ. Попробуйте сократить описание.')
            parts = [part for item in result.get('output', []) if item.get('type') == 'message'
                     for part in item.get('content', [])]
            if any(part.get('type') == 'refusal' for part in parts):
                raise AIError('AI не смог обработать это описание. Заполните форму вручную.', 422)
            value = json.loads(''.join(part['text'] for part in parts if part.get('type') == 'output_text'))
            if not isinstance(value, dict):
                raise ValueError('not an object')
            return value
        except (ValueError, TypeError, KeyError, AttributeError):
            raise AIError('AI вернул некорректный ответ. Попробуйте ещё раз.') from None
    finally:
        _SLOTS.release()
