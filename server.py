"""Локальный веб-сервис: python3 server.py --port 8000."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from explanations import recommend
from matching import normalize_profiles

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
                return self.send(200, meta)
            assets = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                      "/style.css": ("style.css", "text/css")}
            if path not in assets:
                return self.send(404, {"error": "Страница не найдена"})
            filename, mime = assets[path]
            self.send(200, (ROOT / "web" / filename).read_bytes(), mime + "; charset=utf-8")

        def do_POST(self):
            if urlsplit(self.path).path != "/api/recommend":
                return self.send(404, {"error": "Метод не найден"})
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                return self.send(415, {"error": "Ожидается application/json"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    return self.send(413, {"error": "Размер запроса должен быть от 1 до 16384 байт"})
                payload = json.loads(self.rfile.read(length))
                result = recommend(profiles, validate_request(payload))
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
