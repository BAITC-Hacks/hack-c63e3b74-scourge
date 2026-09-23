"""Поиск только по условиям из текста и явно обозначенные близкие варианты."""

from collections import Counter
from datetime import date, timedelta

from ai_ranking import STYLE_INSTRUCTIONS, _preferences, _quality, _schema, _validated_matches
from explanations import amount, choose_excerpt
from matching import normalize_profiles, normalize_request, select_candidates


DATE_CODES = {"date_busy", "date_unavailable", "date_outside_calendar", "date_unknown"}


def _nearest_available(profile, requested):
    """Ищем по всему известному календарю; при равном расстоянии — будущее."""
    current = date.fromisoformat(requested)
    calendar = profile["calendar_range"]
    busy = set(profile["busy_dates"])

    def known_free(day):
        return (day not in busy
                and (calendar is None or calendar["start"] <= day <= calendar["end"]))

    if profile["available_dates"] is not None:
        days = [day for day in profile["available_dates"] if known_free(day)]
    elif calendar is not None:
        start, end = date.fromisoformat(calendar["start"]), date.fromisoformat(calendar["end"])
        pivot = min(max(current, start), end)
        days = []
        # После len(busy) последовательных занятых дней либо найдётся
        # свободный, либо закончится календарь. Не сканируем годы вслепую.
        for distance in range(len(busy) + 1):
            for offset in ((0,) if distance == 0 else (distance, -distance)):
                try:
                    candidate = pivot + timedelta(days=offset)
                except OverflowError:
                    continue
                if start <= candidate <= end and known_free(candidate.isoformat()):
                    days.append(candidate.isoformat())
            if days:
                break
    else:
        return None
    return min(days, key=lambda day: (abs((date.fromisoformat(day) - current).days),
                                     day < requested, day), default=None)


def _differences(profile, query, reasons, matches):
    differences = []
    codes = {reason["code"] for reason in reasons}
    proposed_date = None

    def add(field, requested, actual, message):
        differences.append({"field": field, "requested": requested, "actual": actual,
                            "message": message})

    if codes & DATE_CODES:
        proposed_date = _nearest_available(profile, query["date"])
        reason = ("занят" if "date_busy" in codes else
                  "нет данных календаря" if codes & {"date_unknown", "date_outside_calendar"}
                  else "дата не указана среди доступных")
        message = f"На {query['date']}: {reason}. "
        message += (f"Ближайшая свободная дата по календарю: {proposed_date}."
                    if proposed_date else "Свободная дата не подтверждена; нужно уточнить у исполнителя.")
        add("date", query["date"], proposed_date, message)
    if "over_budget" in codes:
        difference = profile["price"] - query["budget"]
        add("budget", query["budget"], profile["price"],
            f"Цена {amount(profile['price'])} ₸ выше бюджета {amount(query['budget'])} ₸ "
            f"на {amount(difference)} ₸.")
    if "format_mismatch" in codes:
        actual = ", ".join(profile["formats"]) or "не указаны"
        add("format", query["format"], profile["formats"],
            f"Формат «{query['format']}» не указан. Форматы профиля: {actual}; нужно уточнить возможность.")
    if "language_mismatch" in codes:
        wanted = set(query["languages"])
        if query["language"]:
            wanted.add(query["language"])
        missing = sorted(wanted - set(profile["languages"]))
        add("languages", sorted(wanted), profile["languages"],
            f"В профиле не указаны запрошенные языки: {', '.join(missing)}; нужно уточнить.")
    if "duration_exceeded" in codes:
        add("duration_hours", query["duration_hours"], profile["max_hours"],
            f"Вместо {amount(query['duration_hours'])} ч указано максимум {amount(profile['max_hours'])} ч.")
    for match in matches:
        if match["status"] != "supported":
            add("preferences", match["preference"], None,
                f"Пожелание «{match['preference']}» не подтверждено описанием; нужно уточнить.")
    return differences, proposed_date


def _card(profile, query, peers, matches, differences=None, proposed_date=None):
    """Не предполагаем неуказанный бюджет, формат или дату."""
    differences = differences or []
    starting = profile["price_kind"] == "starting"
    currency = "₸" if profile["currency"] == "KZT" else profile["currency"]
    details = [f"{'Цена от' if starting else 'Цена'} {amount(profile['price'])} {currency}"]
    if query["budget"] is not None and profile["price"] <= query["budget"]:
        details[0] += f" — в пределах указанного бюджета {amount(query['budget'])} ₸"
    if starting or profile["price_imputed"]:
        details.append("итоговую стоимость нужно уточнить")
    details.append(f"Город: {profile['city']}")
    if profile["formats"]:
        details.append("форматы в профиле: " + ", ".join(profile["formats"]))
    if profile["languages"]:
        details.append("языки в профиле: " + ", ".join(profile["languages"]))
    details.append("работа не привязана к часам присутствия" if profile["max_hours"] is None else
                   f"присутствие до {amount(profile['max_hours'])} ч")
    if query["date"] is None:
        details.append("дата не указана, доступность не проверялась")
    elif not any(item["field"] == "date" for item in differences):
        basis = ("дата указана среди доступных" if profile["available_dates"] is not None else
                 "дата не отмечена занятой в известном календаре")
        details.append(f"{query['date']} — {basis}")
    elif proposed_date:
        details.append(f"предлагаемая дата {proposed_date} проверена по календарю")
    else:
        details.append("доступность на запрошенную дату не подтверждена")
    excerpt = choose_excerpt(profile, peers)
    if excerpt:
        details.append(f"фрагмент описания: «{excerpt}»")
    notices = []
    for flag, notice in (("team_added", "Добавлен командой"), ("synthetic", "Синтетический профиль"),
                         ("price_imputed", "Цена заполнена при подготовке датасета"),
                         ("city_imputed", "Город заполнен при подготовке датасета")):
        if profile[flag]:
            notices.append(notice)
    return {
        "id": profile["id"], "name": profile["name"], "city": profile["city"],
        "category": query["category"] or ", ".join(profile["categories"]),
        "price": profile["price"], "price_kind": profile["price_kind"], "currency": profile["currency"],
        "explanation": "; ".join(details) + ".", "description_excerpt": excerpt,
        "notices": notices, "synthetic": profile["synthetic"], "team_added": profile["team_added"],
        "style_matches": matches, "style_score": sum(m["status"] == "supported" for m in matches),
        "is_alternative": bool(differences), "differences": differences, "proposed_date": proposed_date,
    }


def assistant_recommend(rows, request, preferences, complete_json):
    """Точные результаты удовлетворяют всем заданным условиям и пожеланиям.

    Пустые поля не ограничивают поиск. Альтернативы сохраняют указанные город
    и категорию, явно перечисляют каждое неподтверждённое условие и никогда
    не заменяют исходный запрос. Ошибка AI не превращает пожелание в совпадение.
    """
    profiles = normalize_profiles(rows)
    query = normalize_request(request, partial=True)
    preferences = _preferences(preferences)
    constrained = preferences or any(value not in (None, []) for value in query.values())
    selected = select_candidates(profiles, query, partial=True, limit=None)
    failures = {item["id"]: item["reasons"] for item in selected["rejected"]}
    local = [profile for profile in profiles
             if (query["city"] is None or profile["city"] == query["city"])
             and (query["category"] is None or query["category"] in profile["categories"])]
    evidence = {profile["id"]: [{"preference": preference, "status": "unknown", "quote": ""}
                                for preference in preferences] for profile in local}
    ai = {"applied": False, "message": "Все указанные условия проверены по данным каталога."}
    if preferences and local:
        try:
            response = complete_json(
                name="style_matches", schema=_schema([p["id"] for p in local], preferences),
                instructions=STYLE_INSTRUCTIONS,
                payload={"preferences": preferences,
                         "profiles": [{"id": p["id"], "description": p["description"]} for p in local]},
            )
            evidence = _validated_matches(response, local, preferences)
            ai = {"applied": True,
                  "message": "AI сопоставил пожелания с описаниями. Цитаты — заявления профилей, детали нужно уточнить у исполнителей."}
        except Exception:
            # Ни ошибки провайдера, ни непроверенные ответы не выдаём за
            # успешную оценку; текст исключения может содержать секреты.
            ai = {"applied": False,
                  "message": "AI не смог проверить пожелания. Точные совпадения не подтверждены; близкие варианты требуют уточнения."}
    elif preferences:
        ai["message"] = "В указанных городе и категории нет профилей для проверки пожеланий."

    exact, alternatives, rejected = [], [], []
    for profile in profiles:
        identifier = profile["id"]
        reasons = list(failures.get(identifier, []))
        if identifier not in evidence:
            rejected.append({"id": identifier, "reasons": reasons})
            continue
        matches = evidence[identifier]
        missing = [match for match in matches if match["status"] != "supported"]
        style_reasons = [{"code": "preference_unconfirmed", "field": "preferences",
                          "expected": match["preference"], "actual": None} for match in missing]
        if not constrained:
            rejected.append({"id": identifier, "reasons": [{"code": "no_requirements"}]})
        elif not reasons and not missing:
            exact.append(profile)
        else:
            rejected.append({"id": identifier, "reasons": reasons + style_reasons})
            differences, proposed_date = _differences(profile, query, reasons, matches)
            date_difference = next((item for item in differences if item["field"] == "date"), None)
            distance = (abs((date.fromisoformat(proposed_date) - date.fromisoformat(query["date"])).days)
                        if proposed_date else float("inf")) if date_difference else 0
            budget_overrun = (max(0, profile["price"] - query["budget"])
                              if query["budget"] is not None else 0)
            alternatives.append({"profile": profile, "matches": matches, "differences": differences,
                                 "proposed_date": proposed_date,
                                 "order": (len(differences), distance, budget_overrun,
                                           -sum(m["status"] == "supported" for m in matches),
                                           profile["price"], identifier)})

    exact.sort(key=lambda profile: (profile["price"], profile["id"]))
    peers = exact[:3]
    cards = [_card(profile, query, peers, evidence[profile["id"]]) for profile in peers]
    for rank, profile in enumerate(exact[3:], start=4):
        rejected.append({"id": profile["id"], "reasons": [{"code": "outside_top_3", "rank": rank}]})
    alternative_cards = []
    if not cards:
        alternatives.sort(key=lambda item: item["order"])
        peers = [item["profile"] for item in alternatives[:3]]
        alternative_cards = [_card(item["profile"], query, peers, item["matches"],
                                   item["differences"], item["proposed_date"]) for item in alternatives[:3]]

    if not constrained:
        message = "Опишите, кого ищете, или укажите хотя бы одно условие события."
    elif exact:
        message = (f"По данным каталога всем указанным в тексте условиям соответствуют: {len(exact)}. "
                   f"Показаны: {len(cards)}.")
    elif alternative_cards:
        message = "Точных совпадений со всеми условиями текста нет. Ниже — ближайшие варианты с явными отличиями."
    else:
        message = "В каталоге нет профилей для указанных города и категории. Уточните город или нужную услугу."
    if constrained and query["date"] is None:
        message += " Дата не указана: доступность нужно проверить отдельно."
    local_ids = set(evidence)
    counts = Counter(reason["code"] for item in rejected if item["id"] in local_ids
                     for reason in item["reasons"] if reason["code"] != "outside_top_3")
    hard_count = selected["eligible_count"] if constrained else 0
    status = ("matched" if cards else
              "category_absent" if query["category"] is not None and not local else "no_matches")
    if status == "category_absent":
        location = f" для города «{query['city']}»" if query["city"] else ""
        message = f"В каталоге{location} нет категории «{query['category']}»."
        recovery_message = "Выберите другой город или категорию: смена даты и бюджета не добавит профили в этот каталог."
    elif not constrained:
        recovery_message = "Укажите, кого ищете, город или другое условие события."
    elif not local:
        recovery_message = "В выбранном городе нет профилей. Выберите другой город."
    else:
        recovery_message = ("Близкие варианты сохраняют указанные город и категорию. "
                            "Отличия перечислены на карточках; исходные условия не изменены."
                            if alternative_cards else "")
    return {
        "cards": cards, "alternatives": alternative_cards,
        "candidates": [item for item in selected["candidates"]
                       if item["profile"]["id"] in {profile["id"] for profile in exact[:3]}],
        "status": status, "message": message,
        "request": query, "preferences": preferences, "request_date": query["date"],
        "total": len(profiles), "eligible_count": len(exact), "hard_match_count": hard_count,
        "city_category_count": len(local), "rejected": sorted(rejected, key=lambda item: item["id"]),
        "exclusion_counts": dict(counts),
        "exclusion_counting": "Учитываются все невыполненные условия; один профиль может иметь несколько причин.",
        "quality": _quality(cards, exact[:3]), "ai": ai,
        "ranking_rule": ("Точные совпадения: все указанные условия и подтверждённые пожелания, затем цена и id. "
                         "Близкие варианты: меньше отличий, ближе дата, меньше превышение бюджета, больше подтверждённых пожеланий, цена и id."),
        "suggestions": [],
        "recovery_message": recovery_message,
    }
