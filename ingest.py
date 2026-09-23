"""Импорт CSV и сверка с HTML-превью HackAlem без выполнения HTML/JavaScript."""
import argparse
import csv
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from matching import date, items, label, normalize_profiles, number


class PreviewParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cards = []
        self.card = None
        self.stack = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "article" and "card" in attrs.get("class", "").split():
            self.card = {}
            self.stack = []
        if self.card is not None and tag not in ("br", "img", "hr", "input", "meta", "link"):
            key = "heading" if tag == "h3" else attrs.get("class", "")
            self.stack.append((tag, key))

    def handle_data(self, data):
        if self.card is not None:
            for _, key in self.stack:
                if key:
                    self.card[key] = self.card.get(key, "") + data

    def handle_endtag(self, tag):
        if self.card is None:
            return
        if tag == "article":
            self.cards.append(self.card)
            self.card = None
            self.stack = []
        elif self.stack and self.stack[-1][0] == tag:
            self.stack.pop()


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("CSV: отсутствуют или дублируются заголовки")
        rows = list(reader)
    if not rows or any(None in row or None in row.values() for row in rows):
        raise ValueError("CSV: пустой файл или неправильное число колонок")
    return rows


def read_preview(path):
    source = Path(path).read_text(encoding="utf-8-sig")
    period = re.search(r"Календарь занятости:\s*(\d{4}-\d{2}-\d{2})\s*—\s*(\d{4}-\d{2}-\d{2})", source)
    if not period:
        raise ValueError("HTML: не найден период календаря")
    parser = PreviewParser()
    parser.feed(source)
    rows = []
    for card in parser.cards:
        identifier = card["id"].strip()
        meta = " ".join(card["meta"].split())
        city, price = meta.split("·", 1)
        attrs = " ".join(card["attrs"].split())
        detail = re.fullmatch(r"Форматы:\s*(.*?)\s*Языки:\s*(.*?)\s*· макс\. на площадке:\s*(.*?)\s*Занято:\s*(\d+) из (\d+) дней, в декабре (\d+) из 31", attrs)
        if not detail:
            raise ValueError(f"HTML: неизвестный формат атрибутов {identifier}")
        formats, languages, hours, busy, days, december = detail.groups()
        rows.append({
            "id": identifier,
            "name": card["heading"].strip().removesuffix(identifier).strip(),
            "categories": items(card["cats"].split("·")),
            "city": label(city.replace("city imputed", "").replace("synthetic", "")),
            "price": number(price.replace("₸", "").replace("*", ""), "price"),
            "city_imputed": "city imputed" in city,
            "synthetic": "synthetic" in city,
            "price_imputed": "*" in price,
            "formats": items(formats), "languages": items(languages),
            "max_hours": None if hours == "не применимо" else number(hours.removesuffix(" ч"), "max_hours"),
            "busy_count": int(busy), "calendar_days": int(days), "december_busy_count": int(december),
            "description_preview": " ".join(card.get("desc", "").split()),
        })
    if not rows or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("HTML: нет карточек или дублируются id")
    return rows, {"start": date(period[1]), "end": date(period[2])}


def prepare(csv_path, html_path):
    profiles = normalize_profiles(read_csv(csv_path))
    preview, period = read_preview(html_path)
    csv_index = {p["id"]: p for p in profiles}
    html_index = {p["id"]: p for p in preview}
    conflicts = []
    from datetime import datetime
    days = (datetime.fromisoformat(period["end"]) - datetime.fromisoformat(period["start"])).days + 1
    for identifier in sorted(csv_index.keys() & html_index.keys()):
        full, partial = csv_index[identifier], html_index[identifier]
        derived = dict(full, busy_count=len(full["busy_dates"]), calendar_days=days,
                       december_busy_count=sum(d.startswith(period["end"][:4] + "-12-") for d in full["busy_dates"]))
        differences = {key: {"csv": derived[key], "html": value}
                       for key, value in partial.items() if key != "description_preview" and derived[key] != value}
        description = " ".join(full["description"].split())
        excerpt = partial["description_preview"]
        if not (description.startswith(excerpt[:-1]) if excerpt.endswith("…") else description == excerpt):
            differences["description_preview"] = {"csv": description, "html": excerpt}
        if differences:
            conflicts.append({"id": identifier, "fields": differences})
    for profile in profiles:
        if any(not period["start"] <= d <= period["end"] for d in profile["busy_dates"]):
            raise ValueError(f"Занятая дата вне периода календаря: {profile['id']}")
        profile["calendar_range"] = period.copy()
    only_csv = sorted(csv_index.keys() - html_index.keys())
    only_html = sorted(html_index.keys() - csv_index.keys())
    report = {"csv_count": len(profiles), "html_count": len(preview),
              "same_ids": not (only_csv or only_html), "only_csv": only_csv, "only_html": only_html,
              "conflicts": conflicts, "preview_consistent": not (only_csv or only_html or conflicts),
              "calendar_range": period, "selected_source": "csv", "merged": False,
              "limitations": ["HTML содержит количества занятых дней, а не конкретные даты.",
                              "Описания HTML проверены как полный текст или сокращённый префикс."]}
    return profiles, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("html", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    args = parser.parse_args()
    profiles, report = prepare(args.csv, args.html)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not report["preview_consistent"]:
        raise SystemExit("Обнаружены расхождения. См. comparison.json; новый profiles.json не записан.")
    (args.output_dir / "profiles.json").write_text(json.dumps(profiles, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
