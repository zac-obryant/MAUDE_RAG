"""Tests for steps 3 to 5. No API key or internet needed: Claude is replaced by stand-ins."""

import sqlite3
from types import SimpleNamespace

import pytest

from maude_rag import llm, router
from maude_rag.agent import recall_url
from maude_rag.evaluate_llm import same_result
from maude_rag.sql import build, run_sql

REPORTS = [
    {"report_number": "R1", "date_received": "20250314", "event_type": "Injury", "brand_name": "Acme Pump",
     "manufacturer": "Acme Inc.", "product_code": "LZG", "narrative": "Pump stopped.",
     "product_problems": ["Pumping Stopped", "Pumping Stopped"]},
    {"report_number": "R2", "date_received": "20250402", "event_type": "Malfunction", "brand_name": "Acme Pump",
     "manufacturer": "ACME INC", "product_code": "LZG", "narrative": "Screen blank.",
     "product_problems": ["No Display/Image"]},
]


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "reports.db"
    build(REPORTS, path)
    return path


def test_database_holds_reports_with_month_and_capitals(db):
    rows = run_sql("SELECT report_number, month, event_type, manufacturer FROM reports ORDER BY 1", db)["rows"]
    assert rows == [("R1", 3, "INJURY", "ACME INC."), ("R2", 4, "MALFUNCTION", "ACME INC")]


def test_repeated_problems_are_stored_once(db):
    assert run_sql("SELECT COUNT(*) FROM problems WHERE report_number = 'R1'", db)["rows"] == [(1,)]


@pytest.mark.parametrize("sql", [
    "DELETE FROM reports",
    "WITH x AS (SELECT 1) DELETE FROM reports",
    "SELECT 1; DROP TABLE reports",
])
def test_queries_cannot_change_the_database(db, sql):
    with pytest.raises((ValueError, sqlite3.Error)):
        run_sql(sql, db)
    assert run_sql("SELECT COUNT(*) FROM reports", db)["rows"] == [(2,)]


def test_long_results_are_cut_off_and_flagged(db, monkeypatch):
    monkeypatch.setattr("maude_rag.sql.MAX_SQL_ROWS", 1)
    out = run_sql("SELECT report_number FROM reports", db)
    assert out["rows"] == [("R1",)] and out["truncated"]


def test_results_match_regardless_of_order_case_and_extra_columns():
    assert same_result([("DEATH", 8), ("INJURY", 704)], [("injury", 704.0), ("death", 8)])
    assert same_result([(8,)], [("DEATH", 8)])  # a label beside the count is fine
    assert not same_result([(8,)], [(9,)])
    assert not same_result([(8,)], [(8,), (1,)])  # extra rows are not


def test_recall_query_covers_all_insulin_pump_codes_and_one_firm():
    url = recall_url("Tandem Diabetes")
    assert "product_code:LZG+product_code:QFG+product_code:OZP+product_code:OZO" in url
    assert 'recalling_firm:"Tandem+Diabetes"' in url and "sort=event_date_initiated:desc" in url


def test_router_drops_filters_the_question_did_not_state(monkeypatch):
    decision = {"route": "search", "reason": "r",
                "filters": {"event_type": "Death", "brand": "", "manufacturer": "", "since": 0, "until": 0}}
    monkeypatch.setattr(router, "ask_claude", lambda *a, **k: decision)
    assert router.route("deaths?")["filters"] == {"event_type": "Death"}


def fake_client(stop_reason, text):
    response = SimpleNamespace(stop_reason=stop_reason, model="claude-opus-5-5",
                               content=[SimpleNamespace(type="text", text=text)])
    create = lambda **kwargs: response
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))


def test_json_answers_are_parsed(monkeypatch):
    monkeypatch.setattr(llm, "client", lambda: fake_client("end_turn", '{"route": "sql"}'))
    assert llm.ask_claude("s", "p", schema={"type": "object"}) == {"route": "sql"}


def test_a_declined_request_raises_instead_of_returning_nothing(monkeypatch):
    monkeypatch.setattr(llm, "client", lambda: fake_client("refusal", ""))
    with pytest.raises(llm.Declined):
        llm.ask_claude("s", "p")


def test_recalls_are_listed_once_per_event_even_with_missing_fields():
    from maude_rag.agent import summarise_recalls

    records = [{"res_event_number": "1", "product_description": None},
               {"res_event_number": "1"}, {"res_event_number": "2"}, {"res_event_number": "3"}]
    text = summarise_recalls(records, max_events=2)
    assert text.count("Recall 1 ") == 1 and "Recall 2 " in text and "Recall 3 " not in text
    assert "(At least 1 older recall events not shown.)" in text


def test_a_cut_off_reply_is_reported_not_parsed(monkeypatch):
    monkeypatch.setattr(llm, "client", lambda: fake_client("max_tokens", '{"route": "sq'))
    with pytest.raises(RuntimeError, match="cut off"):
        llm.ask_claude("s", "p", schema={"type": "object"})


def test_a_runaway_query_is_stopped(db, monkeypatch):
    monkeypatch.setattr("maude_rag.sql.QUERY_SECONDS", 0)
    with pytest.raises(sqlite3.OperationalError):
        run_sql("WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) SELECT COUNT(*) FROM n", db)
