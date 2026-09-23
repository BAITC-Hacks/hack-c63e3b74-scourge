"""Проверяет фиксированные демо-запросы и сохраняет читаемый JSON-отчёт."""
import json
from pathlib import Path
from time import perf_counter

from explanations import recommend


def main():
    root = Path(__file__).resolve().parent
    rows = json.loads((root / "data/profiles.json").read_text(encoding="utf-8"))
    cases = json.loads((root / "examples/quality_requests.json").read_text(encoding="utf-8"))
    report = []
    for case in cases:
        start = perf_counter()
        result = recommend(rows, case["request"])
        elapsed = perf_counter() - start
        ids = [c["id"] for c in result["cards"]]
        if ids != case["expected_ids"] or result["status"] != case["expected_status"]:
            raise AssertionError(f"{case['id']}: результат отличается от зафиксированного")
        if result != recommend(rows[::-1], case["request"]):
            raise AssertionError(f"{case['id']}: результат неповторяем")
        if not result["quality"]["distinct_explanations"]:
            raise AssertionError(f"{case['id']}: объяснения не различаются")
        for suggestion in result["suggestions"]:
            changed = {key for key in set(case["request"]) | set(suggestion["request"])
                       if case["request"].get(key) != suggestion["request"].get(key)}
            retry = recommend(rows, suggestion["request"])
            if (changed != {suggestion["field"]} or retry["status"] != "matched"
                    or retry["eligible_count"] != suggestion["eligible_count"]):
                raise AssertionError(f"{case['id']}: подсказка не подтверждается повторным подбором")
        if elapsed >= 10:
            raise AssertionError(f"{case['id']}: превышен ориентир 10 секунд")
        report.append(dict(id=case["id"], request=case["request"], elapsed_ms=round(elapsed * 1000, 2),
                           status=result["status"], message=result["message"], cards=result["cards"],
                           eligible_count=result["eligible_count"], quality=result["quality"],
                           exclusion_counts=result["exclusion_counts"],
                           suggestions=result["suggestions"], recovery_message=result["recovery_message"]))
        print(f"{case['id']}: {result['status']}, ids={','.join(ids) or '-'}, {elapsed * 1000:.1f} ms")
    target = root / "data/quality_demo_result.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Report: data/quality_demo_result.json")


if __name__ == "__main__":
    main()
