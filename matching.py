"""Нормализация, сверка источников и детерминированный подбор кандидатов."""

import argparse
import json
import math
import re
from datetime import datetime
from pathlib import Path


def number(value, field, nullable=False):
    if value is None and nullable:
        return None
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field}: требуется число")
    if isinstance(value, str):
        value = value.strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field}: требуется число") from exc
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{field}: требуется конечное неотрицательное число")
    return result


def date(value):
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"Некорректная дата: {value!r}")


def label(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Требуется непустая строка")
    return " ".join(value.split()).casefold()


def items(value, transform=label):
    if isinstance(value, str):
        value = value.strip()
        value = json.loads(value) if value.startswith("[") else re.split(r"[|;,\n]", value)
    if not isinstance(value, list):
        raise ValueError("Требуется массив или строка со списком")
    return sorted(set(transform(item) for item in value if item != ""))


def flag(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().casefold() in ("true", "false"):
        return value.strip().casefold() == "true"
    raise ValueError(f"Некорректный логический флаг: {value!r}")


def normalize_profile(row):
    identifier = row["id"]
    if isinstance(identifier, bool) or not isinstance(identifier, (str, int)):
        raise ValueError("id: требуется строка или целое число")
    identifier = str(identifier).strip()
    if not identifier:
        raise ValueError("id не может быть пустым")
    if "busy_dates" not in row and row.get("available_dates") is None:
        raise ValueError("Требуется busy_dates или available_dates")
    max_hours = row["max_hours"]
    if isinstance(max_hours, str) and not max_hours.strip():
        max_hours = None
    price_kind = row.get("price_kind", "starting" if "price_from_kzt" in row else "fixed")
    if price_kind not in ("starting", "fixed"):
        raise ValueError("price_kind: требуется starting или fixed")
    calendar = row.get("calendar_range")
    if calendar is not None:
        calendar = {"start": date(calendar["start"]), "end": date(calendar["end"])}
        if calendar["start"] > calendar["end"]:
            raise ValueError("Некорректный период календаря")
    return {
        "id": identifier,
        "name": str(row.get("name", row.get("anon_name", identifier))).strip(),
        "city": label(row["city"]),
        "categories": items(row["categories"]),
        "available_dates": items(row["available_dates"], date) if row.get("available_dates") is not None else None,
        "busy_dates": items(row["busy_dates"], date) if "busy_dates" in row else [],
        "calendar_range": calendar,
        "price": number(row["price_from_kzt"] if "price_from_kzt" in row else row["price"], "price"),
        "price_kind": price_kind,
        "currency": row.get("currency", "KZT"),
        "formats": items(row["event_formats"] if "event_formats" in row else row["formats"]),
        "languages": items(row["languages"]),
        # Поле обязательно: отсутствие данных не равно отсутствию ограничения.
        "max_hours": number(max_hours, "max_hours", nullable=True),
        "city_imputed": flag(row.get("city_imputed")),
        "price_imputed": flag(row.get("price_imputed")),
        "synthetic": flag(row.get("synthetic")),
        "team_added": flag(row.get("team_added", False)),
        "description": str(row.get("description") or "").strip(),
    }


def normalize_profiles(rows):
    profiles, seen = [], set()
    for index, row in enumerate(rows):
        try:
            profile = normalize_profile(row)
            if profile["id"] in seen:
                raise ValueError(f"Дублирующийся id: {profile['id']}")
            seen.add(profile["id"])
            profiles.append(profile)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Запись {index + 1}: {exc}") from exc
    return sorted(profiles, key=lambda p: p["id"])


def compare_sources(excel_rows, html_rows):
    """Сверяет уже извлечённые строки. Никогда не объединяет источники."""
    left = {p["id"]: p for p in normalize_profiles(excel_rows)}
    right = {p["id"]: p for p in normalize_profiles(html_rows)}
    common = sorted(left.keys() & right.keys())
    conflicts = []
    for identifier in common:
        fields = {
            key: {"excel": left[identifier][key], "html": right[identifier][key]}
            for key in left[identifier]
            if left[identifier][key] != right[identifier][key]
        }
        if fields:
            conflicts.append({"id": identifier, "fields": fields})
    only_excel = sorted(left.keys() - right.keys())
    only_html = sorted(right.keys() - left.keys())
    return {
        "equivalent": not (conflicts or only_excel or only_html),
        "only_excel": only_excel,
        "only_html": only_html,
        "matching_ids": [identifier for identifier in common if left[identifier] == right[identifier]],
        "conflicts": conflicts,
    }


def select_candidates(rows, request):
    profiles = normalize_profiles(rows)
    languages = request.get("languages", [])
    if languages is None:
        languages = []
    if not isinstance(languages, list) or len(languages) > 10:
        raise ValueError("languages: требуется массив до 10 языков")
    languages = [label(value) for value in languages]
    query = {
        "city": label(request["city"]),
        "category": label(request["category"]),
        "date": date(request["date"]),
        "budget": number(request["budget"], "budget"),
        "format": label(request["format"]),
        "language": label(request["language"]) if request.get("language") is not None else None,
        "languages": sorted(set(languages)),
        "duration_hours": number(request.get("duration_hours"), "duration_hours", nullable=True),
    }
    accepted, rejected = [], []
    for profile in profiles:
        reasons = []

        def check(ok, code, field, expected, actual):
            if not ok:
                reasons.append({"code": code, "field": field, "expected": expected, "actual": actual})

        check(profile["city"] == query["city"], "city_mismatch", "city", query["city"], profile["city"])
        check(query["category"] in profile["categories"], "category_mismatch", "categories", query["category"], profile["categories"])
        if profile["calendar_range"] is not None:
            check(profile["calendar_range"]["start"] <= query["date"] <= profile["calendar_range"]["end"],
                  "date_outside_calendar", "calendar_range", query["date"], profile["calendar_range"])
        check(query["date"] not in profile["busy_dates"], "date_busy", "busy_dates", query["date"], profile["busy_dates"])
        if profile["available_dates"] is not None:
            check(query["date"] in profile["available_dates"], "date_unavailable", "available_dates", query["date"], profile["available_dates"])
        check(profile["price"] <= query["budget"], "over_budget", "price", query["budget"], profile["price"])
        check(query["format"] in profile["formats"], "format_mismatch", "formats", query["format"], profile["formats"])
        required_languages = set(query["languages"])
        if query["language"] is not None:
            required_languages.add(query["language"])
        if required_languages:
            check(required_languages.issubset(profile["languages"]), "language_mismatch", "languages",
                  sorted(required_languages), profile["languages"])
        if query["duration_hours"] is not None:
            check(profile["max_hours"] is None or profile["max_hours"] >= query["duration_hours"],
                  "duration_exceeded", "max_hours", query["duration_hours"], profile["max_hours"])
        if reasons:
            rejected.append({"id": profile["id"], "reasons": reasons})
            continue
        # Все предпочтения проверены как обязательные условия. Ранжируем
        # по доле оставшегося бюджета, не выдумывая рейтинг качества.
        remaining = query["budget"] - profile["price"]
        score = 100.0 * (remaining / query["budget"]) if query["budget"] else 100.0
        accepted.append({
            "profile": profile,
            "score": score,
            "facts": {"matched_request": query.copy(), "budget_remaining_at_listed_price": remaining,
                      "presence_unlimited": profile["max_hours"] is None,
                      "availability_basis": "explicit_available_date" if profile["available_dates"] is not None else "not_in_busy_dates",
                      "price_requires_confirmation": profile["price_kind"] == "starting" or profile["price_imputed"] is True,
                      "city_imputed": profile["city_imputed"],
                      "price_imputed": profile["price_imputed"],
                      "synthetic": profile["synthetic"]},
        })
    accepted.sort(key=lambda item: (-item["score"], item["profile"]["id"]))
    for rank, item in enumerate(accepted[3:], start=4):
        rejected.append({"id": item["profile"]["id"], "reasons": [
            {"code": "outside_top_3", "rank": rank, "score": item["score"]}
        ]})
    return {
        "candidates": accepted[:3],
        "rejected": sorted(rejected, key=lambda item: item["id"]),
        "total": len(profiles),
        "eligible_count": len(accepted),
        "ranking_rule": "score = 100 * (budget - price) / budget; при budget=0: 100; затем id по возрастанию как строка",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profiles", type=Path)
    parser.add_argument("request", type=Path)
    args = parser.parse_args()
    result = select_candidates(json.loads(args.profiles.read_text(encoding="utf-8")),
                               json.loads(args.request.read_text(encoding="utf-8")))
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
