# tests/test_home_assistant_budget_bo_analytics.py
from datetime import date

import pytest

import home_assistant_budget_bo_analytics as mod
from home_assistant_budget_bo_analytics import (
    compute_book_metrics,
    effective_day,
    find_due_recurring,
    month_range,
)

TODAY = date(2024, 3, 15)


def tx(d, amount, typ="expense", cat="food"):
    return {"date": d, "amount": amount, "type": typ, "category": cat}


def test_month_range_regular_and_leap():
    assert month_range(2024, 2) == (date(2024, 2, 1), date(2024, 2, 29))
    assert month_range(2023, 2) == (date(2023, 2, 1), date(2023, 2, 28))
    assert month_range(2024, 4)[1] == date(2024, 4, 30)


def test_month_range_december():
    assert month_range(2024, 12) == (date(2024, 12, 1), date(2024, 12, 31))


def test_effective_day():
    assert effective_day(31, 2024, 2) == 29
    assert effective_day(31, 2023, 2) == 28
    assert effective_day(30, 2024, 4) == 30
    assert effective_day(15, 2024, 2) == 15


def test_empty_book():
    r = compute_book_metrics({}, TODAY)
    assert r["total_income"] == 0
    assert r["balance"] == 0
    assert r["transaction_count"] == 0
    assert r["month_label"] == "2024-03"
    assert r["category_breakdown"] == []
    assert r["budget_alerts"] == []
    assert r["recurring_upcoming"] == []
    assert len(r["trend"]) == 6


def test_totals_and_month():
    book = {"transactions": [
        tx("2024-03-01", 100, "income", "salary"),
        tx("2024-03-10", 30.25),
        tx("2024-02-10", 50),
        tx("2024-02-11", 20, "income", "salary"),
    ]}
    r = compute_book_metrics(book, TODAY)
    assert r["total_income"] == 120
    assert r["total_expense"] == pytest.approx(80.25)
    assert r["balance"] == pytest.approx(39.75)
    assert r["month_income"] == 100
    assert r["this_month_count"] == 2
    assert r["transaction_count"] == 4
    assert r["month_balance"] == pytest.approx(69.75)


def test_month_boundaries_inclusive():
    book = {"transactions": [tx("2024-03-01", 1), tx("2024-03-31", 2),
                             tx("2024-04-01", 4), tx("2024-02-29", 8)]}
    r = compute_book_metrics(book, TODAY)
    assert r["month_expense"] == 3
    assert r["this_month_count"] == 2


def test_category_breakdown_sorted_and_usage():
    book = {
        "categories": [{"id": "food", "name": "Food", "icon": "i", "color": "#fff"}],
        "budgets": {"food": 200},
        "transactions": [tx("2024-03-02", 50), tx("2024-03-03", 50),
                         tx("2024-03-04", 500, cat="rent"),
                         tx("2024-03-05", 99, "income", "food")],
    }
    r = compute_book_metrics(book, TODAY)
    bd = r["category_breakdown"]
    assert [b["category_id"] for b in bd] == ["rent", "food"]
    assert bd[0]["name"] == "rent"
    assert bd[0]["icon"] == "mdi:tag"
    assert bd[0]["color"] == "#95A5A6"
    assert bd[0]["usage_pct"] is None
    assert bd[0]["budget"] is None
    assert bd[1]["name"] == "Food"
    assert bd[1]["count"] == 2
    assert bd[1]["amount"] == 100
    assert bd[1]["usage_pct"] == 50.0


def test_zero_budget_no_usage_and_no_alert():
    book = {"budgets": {"food": 0},
            "transactions": [tx("2024-03-02", 10)]}
    r = compute_book_metrics(book, TODAY)
    assert r["category_breakdown"][0]["usage_pct"] is None
    assert r["budget_alerts"] == []


def test_trend_across_year_boundary():
    r = compute_book_metrics({"transactions": [
        tx("2023-11-05", 10), tx("2023-12-05", 5, "income", "s"),
        tx("2023-09-30", 99)]}, date(2024, 2, 10))
    labels = [t["label"] for t in r["trend"]]
    assert labels == ["2023-09", "2023-10", "2023-11", "2023-12",
                      "2024-01", "2024-02"]
    assert r["trend"][0]["expense"] == 99
    assert r["trend"][2]["expense"] == 10
    assert r["trend"][3]["income"] == 5
    assert r["trend"][-1]["year"] == 2024 and r["trend"][-1]["month"] == 2


def test_trend_excludes_older_than_six_months():
    r = compute_book_metrics({"transactions": [tx("2023-09-30", 99)]}, TODAY)
    assert all(t["expense"] == 0 for t in r["trend"])


def test_budget_alert_severities():
    book = {
        "categories": [{"id": "a", "name": "A"}],
        "budgets": {"a": 100, "b": 100, "c": 100, "d": 100},
        "transactions": [
            tx("2024-03-02", 100, cat="a"),
            tx("2024-03-02", 80, cat="b"),
            tx("2024-03-02", 79, cat="c"),
        ],
    }
    r = compute_book_metrics(book, TODAY)
    sev = {a["category_id"]: a["severity"] for a in r["budget_alerts"]}
    assert sev == {"a": "over", "b": "warning", "c": "ok", "d": "ok"}
    assert r["over_budget_count"] == 1
    assert r["warn_budget_count"] == 1
    pcts = [a["pct"] for a in r["budget_alerts"]]
    assert pcts == sorted(pcts, reverse=True)
    assert r["budget_alerts"][0]["category_name"] == "A"
    assert r["budget_alerts"][1]["category_name"] == "b"


def rule(i, day, **kw):
    d = {"id": i, "name": f"r{i}", "amount": 10, "type": "expense",
         "category": "x", "day_of_month": day}
    d.update(kw)
    return d


def test_recurring_upcoming():
    book = {"recurring": [
        rule(1, 20), rule(2, 15), rule(3, 10),
        rule(4, 1, active=False),
        rule(5, 31, last_run_date="2024-02-29"),
    ]}
    r = compute_book_metrics(book, TODAY)["recurring_upcoming"]
    assert [x["id"] for x in r] == [2, 1, 5, 3]
    assert r[0]["days_until"] == 0
    assert r[1]["due_date"] == "2024-03-20"
    assert r[2]["due_date"] == "2024-03-31"
    assert r[3]["due_date"] == "2024-04-10"
    assert r[3]["days_until"] == 26
    assert r[2]["last_run_date"] == "2024-02-29"


def test_recurring_december_rollover_and_clamp():
    r = compute_book_metrics({"recurring": [rule(1, 5)]},
                             date(2024, 12, 20))["recurring_upcoming"]
    assert r[0]["due_date"] == "2025-01-05"
    r = compute_book_metrics({"recurring": [rule(1, 31)]},
                             date(2024, 1, 31))["recurring_upcoming"]
    assert r[0]["days_until"] == 0
    r = compute_book_metrics({"recurring": [rule(1, 30)]},
                             date(2023, 1, 31))["recurring_upcoming"]
    assert r[0]["due_date"] == "2023-02-28"


def test_recurring_limited_to_five():
    book = {"recurring": [rule(i, 16 + i) for i in range(8)]}
    assert len(compute_book_metrics(book, TODAY)["recurring_upcoming"]) == 5


def test_find_due_recurring():
    book = {"recurring": [
        rule(1, 10),
        rule(2, 15),
        rule(3, 20),
        rule(4, 10, active=False),
        rule(5, 10, last_run_date="2024-03-01"),
        rule(6, 10, last_run_date="2024-02-10"),
        rule(7, 10, last_run_date="garbage"),
        rule(8, 10, last_run_date=None),
    ]}
    ids = [r["id"] for r in find_due_recurring(book, TODAY)]
    assert ids == [1, 2, 6, 7, 8]


def test_find_due_clamps_day():
    book = {"recurring": [rule(1, 31)]}
    assert find_due_recurring(book, date(2024, 2, 29)) == book["recurring"]
    assert find_due_recurring(book, date(2024, 2, 28)) == []


def test_find_due_empty():
    assert find_due_recurring({}, TODAY) == []


class _FakeDate(date):
    @classmethod
    def today(cls):
        return date(2024, 3, 15)


def test_compute_defaults_to_today(monkeypatch):
    monkeypatch.setattr(mod, "date", _FakeDate)
    r = mod.compute_book_metrics({})
    assert r["month_label"] == "2024-03"


def test_find_due_defaults_to_today(monkeypatch):
    monkeypatch.setattr(mod, "date", _FakeDate)
    book = {"recurring": [rule(1, 10), rule(2, 20)]}
    assert [r["id"] for r in mod.find_due_recurring(book)] == [1]
