"""Фактические объяснения поверх matching; запуск: python explanations.py profiles request."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re

from matching import date, label, select_candidates


REASONS = {
    "date_outside_calendar": "нет данных календаря на эту дату",
    "date_busy": "заняты на выбранную дату",
    "date_unavailable": "дата не указана среди доступных",
    "over_budget": "указанная цена выше бюджета",
    "format_mismatch": "не указан нужный формат",
    "language_mismatch": "не указан нужный язык",
    "duration_exceeded": "максимальная длительность меньше запрошенной",
}


def amount(value):
    return f"{value:,.2f}".rstrip("0").rstrip(".").replace(",", " ")


def excerpts(description):
    """Только дословные фрагменты, без генерации или приписывания свойств."""
    text = " ".join(description.split())
    parts = re.split(r"(?<=[.!?])\s+|\s*•\s*", text)
    return [part for part in parts if part]


def choose_excerpt(profile, peers):
    parts = excerpts(profile["description"])
    if not parts:
        return None
    # Предпочтение фрагментам, которых нет у других выбранных профилей.
    others = [" ".join(p["description"].split()) for p in peers if p["id"] != profile["id"]]
    concrete = re.compile(
        r"сценари|интерактив|викторин|импровизац|оборудован|репортаж|портрет|"
        r"цвет|композиц|оформлен|опыт|специализ|работает|работаем|вед[её]т|"
        r"снима|съ[её]м|вместим|вмеща|программ", re.IGNORECASE)
    part = min(enumerate(parts), key=lambda pair: (
        not bool(concrete.search(pair[1])),
        sum(pair[1] in other for other in others), pair[0]))[1]
    if len(part) > 200:
        part = part[:197].rsplit(" ", 1)[0] + "…"
    return part


def explain_card(candidate, peers):
    p, q = candidate["profile"], candidate["facts"]["matched_request"]
    currency = "₸" if p["currency"] == "KZT" else p["currency"]
    starting = p["price_kind"] == "starting"
    price = f"{'Цена от' if starting else 'Цена'} {amount(p['price'])} {currency}"
    first = f"{price} не превышает бюджет {amount(q['budget'])} ₸"
    if starting or p["price_imputed"]:
        first += "; итоговую стоимость нужно уточнить"
    details = [f"Формат: {q['format']}"]
    if p["languages"]:
        details.append("языки: " + ", ".join(p["languages"]))
    if p["max_hours"] is None:
        details.append("работа не привязана к часам присутствия")
    else:
        hours = f"до {amount(p['max_hours'])} ч на площадке"
        if q["duration_hours"] is not None:
            hours += f" при запросе {amount(q['duration_hours'])} ч"
        details.append(hours)
    availability = ("дата указана среди доступных" if p["available_dates"] is not None
                    else "дата не отмечена занятой в календаре")
    details.append(f"{q['date']} — {availability}")
    excerpt = choose_excerpt(p, peers)
    if excerpt:
        details.append(f"фрагмент описания: «{excerpt.rstrip('.!?')}»")
    notices = []
    if p["synthetic"]:
        notices.append("Синтетический профиль")
    if p["price_imputed"]:
        notices.append("Цена заполнена при подготовке датасета")
    if p["city_imputed"]:
        notices.append("Город заполнен при подготовке датасета")
    return {
        "id": p["id"], "name": p["name"], "category": q["category"],
        "city": p["city"], "price": p["price"], "price_kind": p["price_kind"],
        "currency": p["currency"], "explanation": first + ". " + "; ".join(details) + ".",
        "description_excerpt": excerpt, "notices": notices,
        "synthetic": p["synthetic"],
    }


def recommend(rows, request):
    """Сохраняет результат matching и дополняет его карточками и сводкой."""
    result = select_candidates(rows, request)
    counts = Counter()
    for rejected in result["rejected"]:
        codes = {reason["code"] for reason in rejected["reasons"]}
        if codes & {"city_mismatch", "category_mismatch", "outside_top_3"}:
            continue
        # Взаимоисключающие группы: календарь, бюджет, формат, язык, часы.
        primary = next(code for code in REASONS if code in codes)
        counts[primary] += 1
    local_count = result["eligible_count"] + sum(counts.values())
    status = ("category_absent" if not local_count else
              "no_matches" if not result["candidates"] else "matched")
    city, category, day = label(request["city"]), label(request["category"]), date(request["date"])
    if status == "category_absent":
        message = f"В каталоге для города «{city}» нет категории «{category}»."
    else:
        message = f"В городе «{city}» профилей категории «{category}»: {local_count}. "
        if counts:
            message += f"Исключены на {day}: " + "; ".join(
                f"{counts[code]} — {text}" for code, text in REASONS.items() if counts[code]) + ". "
        if status == "no_matches":
            message += "Категория есть, но никто не подходит по заданным условиям."
        elif result["eligible_count"] < 3:
            message += f"Подходят: {result['eligible_count']}; это все доступные варианты по заданным условиям."
        else:
            message += f"Подходят: {result['eligible_count']}; показаны первые 3."
    peers = [item["profile"] for item in result["candidates"]]
    cards = [explain_card(item, peers) for item in result["candidates"]]
    def without_names(text):
        for peer in sorted(peers, key=lambda p: -len(p["name"])):
            if peer["name"]:
                text = re.sub(re.escape(peer["name"]), "[имя]", text, flags=re.IGNORECASE)
        return text.casefold()

    signatures = [without_names(card["explanation"]) for card in cards]
    duplicate_texts = Counter(signatures)
    indistinguishable = [card["id"] for card, signature in zip(cards, signatures)
                         if duplicate_texts[signature] > 1]
    return dict(result, cards=cards, status=status, message=message,
                city_category_count=local_count, exclusion_counts=dict(counts),
                exclusion_counting="Каждый профиль учтён один раз по первой причине: календарь, бюджет, формат, язык, часы.",
                quality={"distinct_explanations": not indistinguishable,
                         "indistinguishable_ids": indistinguishable,
                         "message": "Недостаточно различающих фактов в профилях." if indistinguishable else ""})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profiles", type=Path)
    parser.add_argument("request", type=Path)
    args = parser.parse_args()
    print(json.dumps(recommend(json.loads(args.profiles.read_text(encoding="utf-8")),
                               json.loads(args.request.read_text(encoding="utf-8"))),
                     ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
