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
    assert month_range(2024, 12) == (date(2024, 12, 1), date(2024, 12, 31))


def test_month_range_leap_feb():
    assert month_range(2024, 2)[1] == date(2024, 2, 29)
    assert month_range(2023, 2)[1] == date(2023, 2, 28)


def test_effective_day():
    assert effective_day(31, 2023, 2) == 28
    assert effective_day(31, 2024, 2) == 29
    assert effective_day(30, 2024, 4) == 30
    assert effective_day(31, 2024, 4) == 30
    assert effective_day(15, 2024, 2) == 15


def test_empty_book():
    m = compute_book_metrics({}, TODAY)
    assert m["total_income"] == 0
    assert m["balance"] == 0
    assert m["transaction_count"] == 0
    assert m["category_breakdown"] == []
    assert m["budget_alerts"] == []
    assert m["recurring_upcoming"] == []
    assert m["month_label"] == "2024-03"
    assert len(m["trend"]) == 6


def test_totals_and_month():
    book = {"transactions": [
        tx("2024-03-01", 100, "income", "salary"),
        tx("2024-03-10", 40.5),
        tx("2024-02-10", 10),
        tx("2024-03-31", 9.5),
        tx("2024-04-01", 1000),
    ]}
    m = compute_book_metrics(book, TODAY)
    assert m["total_income"] == 100
    assert m["total_expense"] == 1060
    assert m["balance"] == -960
    assert m["month_income"] == 100
    assert m["month_expense"] == 50
    assert m["month_balance"] == 50
    assert m["transaction_count"] == 5
    assert m["this_month_count"] == 3


def test_category_breakdown_sorted_and_budget():
    book = {
        "categories": [{"id": "food", "name": "Food", "icon": "i", "color": "#fff"}],
        "budgets": {"food": 200},
        "transactions": [
            tx("2024-03-02", 50, cat="food"),
            tx("2024-03-03", 100, cat="food"),
            tx("2024-03-04", 300, cat="unknown"),
            tx("2024-03-05", 999, "income", "food"),
        ],
    }
    cb = compute_book_metrics(book, TODAY)["category_breakdown"]
    assert [c["category_id"] for c in cb] == ["unknown", "food"]
    assert cb[0]["name"] == "unknown"
    assert cb[0]["icon"] == "mdi:tag"
    assert cb[0]["color"] == "#95A5A6"
    assert cb[0]["budget"] is None
    assert cb[0]["usage_pct"] is None
    assert cb[1]["name"] == "Food"
    assert cb[1]["amount"] == 150
    assert cb[1]["count"] == 2
    assert cb[1]["usage_pct"] == 75.0


def test_trend_across_year_boundary():
    today = date(2024, 2, 10)
    book = {"transactions": [
        tx("2023-09-30", 5),
        tx("2023-12-15", 20, "income"),
        tx("2024-02-01", 7),
    ]}
    t = compute_book_metrics(book, today)["trend"]
    assert [x["label"] for x in t] == [
        "2023-09", "2023-10", "2023-11", "2023-12", "2024-01", "2024-02"]
    assert t[0]["expense"] == 5
    assert t[3]["income"] == 20
    assert t[5]["expense"] == 7
    assert t[5]["year"] == 2024 and t[5]["month"] == 2


def test_budget_alert_severities():
    book = {
        "categories": [{"id": "a", "name": "A"}],
        "budgets": {"a": 100, "b": 100, "c": 100, "d": 0, "e": -5},
        "transactions": [
            tx("2024-03-01", 100, cat="a"),
            tx("2024-03-01", 80, cat="b"),
            tx("2024-03-01", 79, cat="c"),
            tx("2024-02-01", 500, cat="c"),
        ],
    }
    m = compute_book_metrics(book, TODAY)
    al = m["budget_alerts"]
    assert [a["category_id"] for a in al] == ["a", "b", "c"]
    assert [a["severity"] for a in al] == ["over", "warning", "ok"]
    assert al[0]["category_name"] == "A"
    assert al[1]["category_name"] == "b"
    assert al[2]["pct"] == 79.0
    assert m["over_budget_count"] == 1
    assert m["warn_budget_count"] == 1


def test_recurring_upcoming():
    book = {"recurring": [
        {"id": "1", "name": "Rent", "amount": 1, "type": "expense",
         "category": "h", "day_of_month": 20},
        {"id": "2", "name": "Gym", "amount": 1, "type": "expense",
         "category": "h", "day_of_month": 10, "last_run_date": "2024-03-10"},
        {"id": "3", "name": "Off", "amount": 1, "type": "expense",
         "category": "h", "day_of_month": 16, "active": False},
        {"id": "4", "name": "Today", "amount": 1, "type": "expense",
         "category": "h", "day_of_month": 15},
    ]}
    r = compute_book_metrics(book, TODAY)["recurring_upcoming"]
    assert [x["id"] for x in r] == ["4", "1", "2"]
    assert r[0]["days_until"] == 0
    assert r[1]["due_date"] == "2024-03-20"
    assert r[2]["due_date"] == "2024-04-10"
    assert r[2]["days_until"] == 26
    assert r[2]["last_run_date"] == "2024-03-10"


def test_recurring_december_rollover_and_clamp():
    book = {"recurring": [
        {"id": "1", "name": "x", "amount": 1, "type": "expense",
         "category": "c", "day_of_month": 5},
    ]}
    r = compute_book_metrics(book, date(2024, 12, 20))["recurring_upcoming"]
    assert r[0]["due_date"] == "2025-01-05"
    book["recurring"][0]["day_of_month"] = 31
    r = compute_book_metrics(book, date(2024, 1, 31))["recurring_upcoming"]
    assert r[0]["due_date"] == "2024-01-31"
    r = compute_book_metrics(book, date(2023, 1, 31 - 0))["recurring_upcoming"]
    assert r[0]["days_until"] == 0
    book["recurring"][0]["day_of_month"] = 30
    r = compute_book_metrics(book, date(2023, 1, 31))["recurring_upcoming"]
    assert r[0]["due_date"] == "2023-02-28"


def test_recurring_limited_to_five():
    book = {"recurring": [
        {"id": str(i), "name": "n", "amount": 1, "type": "expense",
         "category": "c", "day_of_month": i + 1}
        for i in range(8)
    ]}
    assert len(compute_book_metrics(book, TODAY)["recurring_upcoming"]) == 5


def test_find_due_basic():
    rules = [
        {"id": "a", "day_of_month": 10},
        {"id": "b", "day_of_month": 15},
        {"id": "c", "day_of_month": 16},
        {"id": "d", "day_of_month": 1, "active": False},
        {"id": "e", "day_of_month": 1, "last_run_date": "2024-03-02"},
        {"id": "f", "day_of_month": 1, "last_run_date": "2024-02-02"},
        {"id": "g", "day_of_month": 1, "last_run_date": "2023-03-02"},
        {"id": "h", "day_of_month": 1, "last_run_date": "garbage"},
        {"id": "i", "day_of_month": 1, "last_run_date": None},
    ]
    due = find_due_recurring({"recurring": rules}, TODAY)
    assert [r["id"] for r in due] == ["a", "b", "f", "g", "h", "i"]


def test_find_due_clamped_day():
    book = {"recurring": [{"id": "a", "day_of_month": 31}]}
    assert find_due_recurring(book, date(2024, 2, 29)) == book["recurring"]
    assert find_due_recurring(book, date(2024, 2, 28)) == []


def test_find_due_empty():
    assert find_due_recurring({}, TODAY) == []


def test_default_today_used():
    assert "month_label" in compute_book_metrics({})
    assert find_due_recurring({}) == []
