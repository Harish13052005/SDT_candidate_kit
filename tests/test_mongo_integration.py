"""Optional integration checks against a disposable MongoDB database.

Set TEST_MONGO_URI to enable these tests. They load only sample data into a
uniquely named database and drop that database when the test finishes.
"""
import os
import pathlib
import uuid

import pytest
from bson import json_util
from fastapi.testclient import TestClient
from pymongo import MongoClient

import app.main as main_module


@pytest.fixture()
def mongo_api_client(monkeypatch):
    uri = os.getenv("TEST_MONGO_URI")
    if not uri:
        pytest.skip("Set TEST_MONGO_URI to run MongoDB integration tests")

    mongo_client = MongoClient(uri, tz_aware=True, serverSelectionTimeoutMS=5000)
    mongo_client.admin.command("ping")
    db_name = f"sdt_candidate_kit_test_{uuid.uuid4().hex}"
    test_db = mongo_client[db_name]
    sample_data = pathlib.Path(__file__).parent.parent / "sample_data"

    for collection in ("employees", "attendance_logs"):
        docs = json_util.loads(
            (sample_data / f"{collection}.json").read_text(encoding="utf-8"),
            json_options=json_util.JSONOptions(tz_aware=True),
        )
        if docs:
            test_db[collection].insert_many(docs)

    monkeypatch.setattr(main_module, "client", mongo_client)
    monkeypatch.setattr(main_module, "db", test_db)
    try:
        with TestClient(main_module.app) as api_client:
            yield api_client, test_db
    finally:
        mongo_client.drop_database(db_name)
        mongo_client.close()


def test_analytics_and_explain_endpoints_use_mongodb(mongo_api_client):
    api, test_db = mongo_api_client
    requests = {
        "employee_monthly": "/analytics/employees/EMP0001/monthly?month=2026-07",
        "department_summary": "/analytics/departments/summary?month=2026-07",
        "late_leaderboard": "/analytics/leaderboard/late?month=2026-07",
        "department_trend": (
            "/analytics/departments/Engineering/trend"
            "?from=2026-07-06&to=2026-07-12"
        ),
        "attendance_list_explain": "/admin/explain/attendance_list?page=1&page_size=5",
        "employee_monthly_explain": (
            "/admin/explain/employee_monthly?emp_code=EMP0001&month=2026-07"
        ),
        "department_summary_explain": (
            "/admin/explain/department_summary?month=2026-07"
        ),
        "late_leaderboard_explain": (
            "/admin/explain/late_leaderboard?month=2026-07"
        ),
        "department_trend_explain": (
            "/admin/explain/department_trend?department=Engineering"
            "&from=2026-07-06&to=2026-07-12"
        ),
    }

    for name, path in requests.items():
        response = api.get(path)
        assert response.status_code == 200, f"{name}: {response.text}"

    trend = api.get(requests["department_trend"]).json()["items"]
    assert len(trend) == 7
    assert [row["date"] for row in trend] == [
        "2026-07-06",
        "2026-07-07",
        "2026-07-08",
        "2026-07-09",
        "2026-07-10",
        "2026-07-11",
        "2026-07-12",
    ]

    expected_indexes = {
        "employees": {"emp_code_1", "department_1_joined_on_1", "joined_on_1"},
        "attendance_logs": {
            "emp_code_1_date_1",
            "date_-1_emp_code_1",
            "emp_code_1_punch_in_-1",
            "emp_code_1_punch_out_1_punch_in_-1",
            "date_1_late_minutes_1",
        },
    }
    for collection, expected in expected_indexes.items():
        actual = {index["name"] for index in test_db[collection].list_indexes()}
        assert expected <= actual
