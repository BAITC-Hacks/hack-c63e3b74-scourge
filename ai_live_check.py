"""Живая проверка AI через HTTP; вызывает OpenAI и расходует API-баланс.

Запускать отдельно: python3 ai_live_check.py. Ключ берётся из .env/окружения
сервером и не печатается. Обычная команда unittest этот файл не запускает.
"""

import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from time import perf_counter

from matching import select_candidates
from server import load_profiles, make_handler


CASES = [
    ("partial", "Нужен ведущий в Алматы",
     {"city": "алматы", "category": "ведущий", "format": None, "date": None,
      "budget": None, "duration_hours": None, "languages": []}),
    ("style", "Нужен ведущий в Алматы на свадьбу 6 октября 2026 года, до 3 млн тенге, "
     "на 5 часов, русский язык. Хочу музыкальные викторины.",
     {"city": "алматы", "category": "ведущий", "format": "свадьба", "date": "2026-10-06",
      "budget": 3000000, "duration_hours": 5, "languages": ["русский"]}),
    ("clarification", "Нужен фотограф в Алматы на 14 ноября, год пока не определён.",
     {"city": "алматы", "category": "фотограф", "format": None, "date": None,
      "budget": None, "duration_hours": None, "languages": []}),
]


def check_result(name, response, expected, profiles):
    parsed, result = response['parsed'], response['result']
    for field, value in expected.items():
        assert parsed['request'][field] == value, f"{name}: неверно извлечено поле {field}"
    if name == 'clarification':
        assert not parsed['ready'] and parsed['questions'] and result is None
        return
    assert parsed['ready'] and result is not None
    if name == 'style':
        assert parsed['preferences'], 'Потеряны явно указанные пожелания'
        assert result['ai']['applied'], 'Модель не проверила пожелания'
    else:
        assert parsed['preferences'] == []
        assert len(result['cards']) == 3
    assert len(result['cards']) <= 3 and len(result['alternatives']) <= 3
    assert not (result['cards'] and result['alternatives'])
    index = {p['id']: p for p in profiles}
    for card in result['cards']:
        selected = select_candidates([index[card['id']]], parsed['request'], partial=True)
        assert selected['eligible_count'] == 1, 'Карточка нарушает обязательные условия'
        assert all(match['status'] == 'supported' for match in card['style_matches'])
    for card in result['cards'] + result['alternatives']:
        for match in card['style_matches']:
            if match['status'] == 'supported':
                assert match['quote'] in ' '.join(index[card['id']]['description'].split())
    for card in result['alternatives']:
        assert card['differences'], 'Альтернатива не объясняет отличия'
        if card['proposed_date']:
            selected = select_candidates([index[card['id']]], {'date': card['proposed_date']}, partial=True)
            assert selected['eligible_count'] == 1, 'Предлагаемая дата не проходит проверку'


def main():
    profiles = load_profiles()
    server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(profiles))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for name, text, expected in CASES:
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=110)
            start = perf_counter()
            try:
                connection.request('POST', '/api/ai/search', json.dumps({'text': text}),
                                   {'Content-Type': 'application/json'})
                response = connection.getresponse()
                body = json.loads(response.read())
                if response.status != 200:
                    raise AssertionError(f"{name}: HTTP {response.status}: {body.get('error', 'ошибка')}")
            finally:
                connection.close()
            elapsed = perf_counter() - start
            check_result(name, body, expected, profiles)
            result = body['result']
            details = (f"cards={len(result['cards'])}, alternatives={len(result['alternatives'])}"
                       if result else 'уточняющий вопрос')
            print(f"{name}: OK, {elapsed:.2f} s, {details}", flush=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
