# tests/test_home_assistant_budget_bo_analytics.py
from datetime import date

import pytest

from home_assistant_budget_bo_analytics import (
    compute_book_metrics,
    effective_day,
    find_due_recurring,
    month_range,
)

TODAY = date(2024, 3, 15)


def tx(d, amount, type_="expense", cat="food"):
    return {"date": d, "amount": amount, "type": type_, "category": cat}


def test_month_range_regular():
    assert month_range(2024, 4) == (date(2024, 4, 1), date(2024, 4, 30))


def test_month_range_december():
    assert month_range(2023, 12) == (date(2023, 12, 1), date(2023, 12, 31))


def test_month_range_leap_feb():
    assert month_range(2024, 2)[1] == date(2024, 2, 29)
    assert month_range(2023, 2)[1] == date(2023, 2, 28)


def test_effective_day():
    assert effective_day(31, 2023, 2) == 28
    assert effective_day(31, 2024, 2) == 29
    assert effective_day(30, 2024, 4) == 30
    assert effective_day(15, 2024, 2) == 15


def test_empty_book():
    r = compute_book_metrics({}, today=TODAY)
    assert r["total_income"] == 0
    assert r["balance"] == 0
    assert r["month_label"] == "2024-03"
    assert r["transaction_count"] == 0
    assert r["category_breakdown"] == []
    assert r["budget_alerts"] == []
    assert r["recurring_upcoming"] == []
    assert len(r["trend"]) == 6


def test_totals_and_month():
    book = {"transactions": [
        tx("2024-03-01", 100, "income", "salary"),
        tx("2024-03-10", 40.5),
        tx("2024-02-10", 10),
        tx("2024-04-01", 5),
    ]}
    r = compute_book_metrics(book, today=TODAY)
    assert r["total_income"] == 100
    assert r["total_expense"] == 55.5
    assert r["balance"] == 44.5
    assert r["month_income"] == 100
    assert r["month_expense"] == 40.5
    assert r["month_balance"] == 59.5
    assert r["transaction_count"] == 4
    assert r["this_month_count"] == 2


def test_month_boundaries_inclusive():
    book = {"transactions": [tx("2024-03-01", 1), tx("2024-03-31", 2), tx("2024-02-29", 4)]}
    r = compute_book_metrics(book, today=TODAY)
    assert r["month_expense"] == 3


def test_trend_order_and_year_wrap():
    book = {"transactions": [tx("2023-12-05", 7), tx("2024-01-05", 3, "income")]}
    r = compute_book_metrics(book, today=date(2024, 2, 10))
    labels = [t["label"] for t in r["trend"]]
    assert labels == ["2023-09", "2023-10", "2023-11", "2023-12", "2024-01", "2024-02"]
    assert r["trend"][3]["expense"] == 7
    assert r["trend"][4]["income"] == 3
    assert r["trend"][0]["year"] == 2023 and r["trend"][0]["month"] == 9


def test_category_breakdown_sorted_and_defaults():
    book = {
        "categories": [{"id": "food", "name": "Food", "icon": "i", "color": "#fff"}],
        "budgets": {"food": 200},
        "transactions": [
            tx("2024-03-02", 50, cat="food"),
            tx("2024-03-03", 50, cat="food"),
            tx("2024-03-04", 300, cat="unknown"),
            tx("2024-03-05", 999, "income", "food"),
        ],
    }
    r = compute_book_metrics(book, today=TODAY)
    cb = r["category_breakdown"]
    assert [c["category_id"] for c in cb] == ["unknown", "food"]
    assert cb[0]["name"] == "unknown"
    assert cb[0]["icon"] == "mdi:tag"
    assert cb[0]["color"] == "#95A5A6"
    assert cb[0]["budget"] is None and cb[0]["usage_pct"] is None
    assert cb[1]["name"] == "Food"
    assert cb[1]["amount"] == 100
    assert cb[1]["count"] == 2
    assert cb[1]["usage_pct"] == 50.0


def test_zero_budget_no_usage():
    book = {"budgets": {"food": 0}, "transactions": [tx("2024-03-02", 5)]}
    r = compute_book_metrics(book, today=TODAY)
    assert r["category_breakdown"][0]["usage_pct"] is None
    assert r["budget_alerts"] == []


def test_budget_alerts_severity():
    book = {
        "categories": [{"id": "a", "name": "A"}],
        "budgets": {"a": 100, "b": 100, "c": 100, "d": 100},
        "transactions": [
            tx("2024-03-02", 100, cat="a"),
            tx("2024-03-02", 80, cat="b"),
            tx("2024-03-02", 79, cat="c"),
        ],
    }
    r = compute_book_metrics(book, today=TODAY)
    sev = {a["category_id"]: a["severity"] for a in r["budget_alerts"]}
    assert sev == {"a": "over", "b": "warning", "c": "ok", "d": "ok"}
    assert [a["category_id"] for a in r["budget_alerts"]][0] == "a"
    assert r["budget_alerts"][0]["category_name"] == "A"
    assert r["budget_alerts"][-1]["pct"] == 0
    assert r["over_budget_count"] == 1
    assert r["warn_budget_count"] == 1


def rule(id_, day, **kw):
    d = {"id": id_, "name": id_, "amount": 10, "type": "expense",
         "category": "food", "day_of_month": day}
    d.update(kw)
    return d


def test_recurring_upcoming():
    book = {"recurring": [
        rule("later", 20),
        rule("today", 15),
        rule("past", 10),
        rule("off", 16, active=False),
    ]}
    r = compute_book_metrics(book, today=TODAY)
    ru = r["recurring_upcoming"]
    assert [x["id"] for x in ru] == ["today", "later", "past"]
    assert ru[0]["days_until"] == 0
    assert ru[1]["due_date"] == "2024-03-20"
    assert ru[2]["due_date"] == "2024-04-10"
    assert ru[2]["days_until"] == 26
    assert ru[0]["last_run_date"] is None


def test_recurring_december_rollover_and_clamp():
    book = {"recurring": [rule("a", 5)]}
    r = compute_book_metrics(book, today=date(2023, 12, 20))
    assert r["recurring_upcoming"][0]["due_date"] == "2024-01-05"
    book = {"recurring": [rule("a", 31)]}
    r = compute_book_metrics(book, today=date(2024, 2, 29))
    assert r["recurring_upcoming"][0]["due_date"] == "2024-02-29"
    r = compute_book_metrics(book, today=date(2024, 1, 31))
    assert r["recurring_upcoming"][0]["days_until"] == 0


def test_recurring_limited_to_five():
    book = {"recurring": [rule(str(i), 16 + i) for i in range(8)]}
    r = compute_book_metrics(book, today=TODAY)
    assert len(r["recurring_upcoming"]) == 5


def test_find_due_basic():
    book = {"recurring": [
        rule("due", 10),
        rule("exact", 15),
        rule("future", 16),
        rule("inactive", 1, active=False),
    ]}
    ids = [r["id"] for r in find_due_recurring(book, TODAY)]
    assert ids == ["due", "exact"]


def test_find_due_last_run():
    book = {"recurring": [
        rule("ran", 1, last_run_date="2024-03-02"),
        rule("old", 1, last_run_date="2024-02-02"),
        rule("otheryear", 1, last_run_date="2023-03-02"),
        rule("bad", 1, last_run_date="garbage"),
        rule("none", 1, last_run_date=None),
    ]}
    ids = [r["id"] for r in find_due_recurring(book, TODAY)]
    assert ids == ["old", "otheryear", "bad", "none"]


def test_find_due_clamped_day():
    book = {"recurring": [rule("eom", 31)]}
    assert find_due_recurring(book, date(2023, 2, 27)) == []
    assert len(find_due_recurring(book, date(2023, 2, 28))) == 1


def test_find_due_empty():
    assert find_due_recurring({}, TODAY) == []


def test_default_today_runs():
    assert "month_label" in compute_book_metrics({})
    assert find_due_recurring({}) == []
