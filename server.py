"""Локальный веб-сервис: python3 server.py --port 8000."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from explanations import compare_dates, recommend
from matching import normalize_profiles
from ai_client import AIError, complete_json, public_status
from ai_brief import parse_brief, strings
from ai_ranking import recommend_with_style
from assistant_search import assistant_recommend

ROOT = Path(__file__).resolve().parent


def load_profiles():
    rows = json.loads((ROOT / "data/profiles.json").read_text(encoding="utf-8"))
    for row in rows:
        row["team_added"] = False
    extra = json.loads((ROOT / "data/team_profiles.json").read_text(encoding="utf-8"))
    for row in extra:
        row["team_added"] = True
    return normalize_profiles(rows + extra)


def validate_request(value):
    if not isinstance(value, dict):
        raise ValueError("Запрос должен быть JSON-объектом")
    for key in ("city", "category", "date", "format"):
        if not isinstance(value.get(key), str) or not value[key].strip() or len(value[key]) > 100:
            raise ValueError(f"Заполните поле {key} (до 100 символов)")
    if "budget" not in value:
        raise ValueError("Укажите бюджет")
    if value.get("language") is not None and (not isinstance(value["language"], str) or len(value["language"]) > 100):
        raise ValueError("Некорректный язык")
    if value.get("languages") is not None:
        strings(value['languages'], count=10, length=100)
    return value


def make_handler(profiles):
    cases = json.loads((ROOT / "examples/quality_requests.json").read_text(encoding="utf-8"))
    meta = {"cities": sorted({p["city"] for p in profiles}),
            "categories": sorted({c for p in profiles for c in p["categories"]}),
            "formats": sorted({f for p in profiles for f in p["formats"]}),
            "languages": sorted({l for p in profiles for l in p["languages"]}),
            "total": len(profiles), "team_count": sum(bool(p["team_added"]) for p in profiles),
            "demos": [{"id": case["id"], "request": case["request"]} for case in cases]}

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, body, content_type="application/json; charset=utf-8"):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/api/meta":
                return self.send(200, dict(meta, ai=public_status()))
            assets = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                      "/style.css": ("style.css", "text/css")}
            if path not in assets:
                return self.send(404, {"error": "Страница не найдена"})
            filename, mime = assets[path]
            self.send(200, (ROOT / "web" / filename).read_bytes(), mime + "; charset=utf-8")

        def do_POST(self):
            path = urlsplit(self.path).path
            if path not in ("/api/recommend", "/api/compare", "/api/ai/parse", "/api/ai/recommend", "/api/ai/search"):
                return self.send(404, {"error": "Метод не найден"})
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                return self.send(415, {"error": "Ожидается application/json"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    return self.send(413, {"error": "Размер запроса должен быть от 1 до 16384 байт"})
                payload = json.loads(self.rfile.read(length))
                if path in ("/api/ai/parse", "/api/ai/search"):
                    if not isinstance(payload, dict):
                        raise ValueError("Запрос должен быть JSON-объектом")
                    parsed = parse_brief(profiles, payload.get('text'), complete_json,
                                         partial=path == '/api/ai/search')
                    parsed['model'] = public_status()['model']
                    if path == '/api/ai/parse':
                        return self.send(200, parsed)
                    result = (assistant_recommend(profiles, parsed['request'], parsed['preferences'], complete_json)
                              if parsed['ready'] else None)
                    if result is not None:
                        result['ai']['model'] = public_status()['model']
                    return self.send(200, {'parsed': parsed, 'result': result})
                request = validate_request(payload)
                if path == "/api/compare":
                    other_date = request.get("compare_date")
                    if not isinstance(other_date, str) or not 0 < len(other_date) <= 100:
                        raise ValueError("Укажите compare_date для сравнения дат")
                    result = compare_dates(profiles, request, other_date)
                elif path == '/api/ai/recommend':
                    preferences = strings(request.get('preferences', []), count=5, length=200)
                    # Validate hard constraints before attempting a model call.
                    base = recommend(profiles, request)
                    try:
                        result = recommend_with_style(profiles, request, preferences, complete_json)
                        result['ai']['model'] = public_status()['model']
                    except (AIError, ValueError) as exc:
                        result = base
                        result['ai'] = {'applied': False,
                                        'message': 'AI-пожелания сейчас не оценены. Показан обычный подбор по цене; обязательные условия соблюдены.'}
                        if isinstance(exc, AIError):
                            result['ai']['message'] += ' ' + str(exc)
                else:
                    result = recommend(profiles, request)
            except AIError as exc:
                return self.send(exc.status, {'error': str(exc)})
            except (ValueError, KeyError, TypeError, OverflowError, RecursionError) as exc:
                return self.send(400, {"error": "Некорректные параметры: " + str(exc)[:180]})
            self.send(200, result)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(load_profiles()))
    print(f"Открыть http://{args.host}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
