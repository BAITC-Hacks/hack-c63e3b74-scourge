"""Проверенные изменения одного условия для пустой выдачи."""

from datetime import date, timedelta

from matching import label, normalize_profiles, select_candidates


def recovery_suggestions(rows, request, result):
    if result["status"] != "no_matches":
        return []
    local = [p for p in normalize_profiles(rows)
             if p["city"] == label(request["city"])
             and label(request["category"]) in p["categories"]]
    failures = {item["id"]: {r["code"] for r in item["reasons"]}
                for item in result["rejected"]}
    suggestions = []

    def verify(field, value, title):
        query = dict(request, **{field: value})
        if field == 'languages' and value == []:
            query['language'] = None
        count = select_candidates(local, query)["eligible_count"]
        if not count:
            return False
        suggestions.append({"field": field, "value": value, "request": query,
                            "label": title, "eligible_count": count,
                            "message": f"Подходящих профилей: {count}. Остальные условия сохранены."})
        return True

    # Ближайшая дата в пределах недели; при равном расстоянии — будущая.
    # Не предлагаем даты за пределами известного календаря профиля.
    current = date.fromisoformat(result["request_date"])
    for distance in range(1, 8):
        found = False
        for offset in (distance, -distance):
            try:
                day = (current + timedelta(days=offset)).isoformat()
            except OverflowError:
                continue
            known = [p for p in local if
                     (p["calendar_range"] is not None
                      and p["calendar_range"]["start"] <= day <= p["calendar_range"]["end"])
                     or (p["available_dates"] is not None and day in p["available_dates"])]
            if (known and select_candidates(known, dict(request, date=day))["eligible_count"]
                    and verify("date", day, f"Проверить дату {day}")):
                found = True
                break
        if found:
            break

    # Рассматриваем только профили, которым мешает ровно одно условие.
    over_budget = [p["price"] for p in local if failures[p["id"]] == {"over_budget"}]
    if over_budget:
        budget = min(over_budget)
        price = f"{budget:,.2f}".rstrip("0").rstrip(".").replace(",", " ")
        verify("budget", budget, f"Бюджет {price} ₸ — по цене «от»")
    if request.get("languages"):
        verify("languages", [], "Не ограничивать языки")
    elif request.get("language") is not None:
        verify("language", None, "Не ограничивать язык")
    shorter = [p["max_hours"] for p in local
               if failures[p["id"]] == {"duration_exceeded"}]
    if shorter:
        hours = max(shorter)
        verify("duration_hours", hours, f"Сократить длительность до {hours:g} ч")
    return suggestions
