"""
API integration tests using mongomock to simulate MongoDB.
The fixture patches app.main.db with a mongomock database that has
the same unique indexes the production lifespan creates.
"""
import pytest
import mongomock
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app


def _create_indexes(mdb):
    """Mirror the indexes created by the lifespan startup handler."""
    mdb.employees.create_index([("emp_code", 1)], unique=True)
    mdb.employees.create_index([("department", 1), ("joined_on", 1)])
    mdb.employees.create_index([("joined_on", 1)])
    mdb.attendance_logs.create_index([("emp_code", 1), ("date", 1)], unique=True)
    mdb.attendance_logs.create_index([("date", -1), ("emp_code", 1)])
    mdb.attendance_logs.create_index([("emp_code", 1), ("punch_in", -1)])
    mdb.attendance_logs.create_index([("emp_code", 1), ("punch_out", 1), ("punch_in", -1)])
    mdb.attendance_logs.create_index([("date", 1), ("late_minutes", 1)])


@pytest.fixture()
def api_client(monkeypatch):
    """Return a TestClient backed by a fresh mongomock database with all indexes."""
    mock_client = mongomock.MongoClient()
    mock_db = mock_client["test_db"]
    _create_indexes(mock_db)
    monkeypatch.setattr(main_module, "client", mock_client)
    monkeypatch.setattr(main_module, "db", mock_db)
    return TestClient(app, raise_server_exceptions=False)


# --------------------------------------------------------------------------- #
# Helper seed functions
# --------------------------------------------------------------------------- #
EMPLOYEE_PAYLOAD = {
    "emp_code": "EMP0001",
    "name": "Asha Rao",
    "email": "asha@example.com",
    "department": "Engineering",
    "shift_start": "09:30",
    "shift_end": "18:30",
    "joined_on": "2026-01-05",
}

# 2026-07-06 09:28:00 IST = 2026-07-06 03:58:00 UTC = 1783310280000 ms
PIN_MS = 1783310280000
# 2026-07-06 18:35:00 IST = 2026-07-06 13:05:00 UTC = 1783343100000 ms
POUT_MS = 1783343100000


def seed_employee(client):
    return client.post("/employees", json=EMPLOYEE_PAYLOAD)


def seed_punch_in(client):
    return client.post("/attendance/punch-in", json={
        "emp_code": "EMP0001",
        "punched_at": PIN_MS,
        "status": "PRESENT",
    })


# --------------------------------------------------------------------------- #
# /health
# --------------------------------------------------------------------------- #
def test_health(api_client):
    res = api_client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_startup_fails_when_index_creation_fails(monkeypatch):
    class FailingCollection:
        def create_index(self, *args, **kwargs):
            raise RuntimeError("index creation failed")

    class FailingDatabase:
        employees = FailingCollection()

    monkeypatch.setattr(main_module, "db", FailingDatabase())
    with pytest.raises(RuntimeError, match="index creation failed"):
        with TestClient(app):
            pass


@pytest.mark.parametrize(
    "path",
    [
        "/attendance?date_from=2026-02-31",
        "/analytics/departments/Engineering/trend?from=2026-02-31&to=2026-03-01",
    ],
)
def test_invalid_calendar_dates_return_422(api_client, path):
    assert api_client.get(path).status_code == 422


# --------------------------------------------------------------------------- #
# /employees
# --------------------------------------------------------------------------- #
def test_create_employee_success(api_client):
    res = seed_employee(api_client)
    assert res.status_code == 201
    data = res.json()
    assert data["emp_code"] == "EMP0001"
    assert "_id" not in data
    assert "created_at" in data


def test_create_employee_duplicate_409(api_client):
    seed_employee(api_client)
    res = api_client.post("/employees", json=EMPLOYEE_PAYLOAD)
    assert res.status_code == 409


def test_create_employee_invalid_emp_code_422(api_client):
    bad = dict(EMPLOYEE_PAYLOAD, emp_code="BADCODE")
    res = api_client.post("/employees", json=bad)
    assert res.status_code == 422


def test_create_employee_shift_equal_422(api_client):
    bad = dict(EMPLOYEE_PAYLOAD, emp_code="EMP0002", shift_end="09:30")
    res = api_client.post("/employees", json=bad)
    assert res.status_code == 422


def test_list_employees_pagination(api_client):
    seed_employee(api_client)
    # Second employee
    api_client.post("/employees", json=dict(EMPLOYEE_PAYLOAD, emp_code="EMP0002", email="b@b.com"))

    # Page 1
    res = api_client.get("/employees?page=1&page_size=1")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert len(data["items"]) == 1
    assert data["items"][0]["emp_code"] == "EMP0001"   # sorted by emp_code

    # Page 2
    res2 = api_client.get("/employees?page=2&page_size=1")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["items"][0]["emp_code"] == "EMP0002"


def test_list_employees_department_filter(api_client):
    seed_employee(api_client)
    api_client.post("/employees", json=dict(
        EMPLOYEE_PAYLOAD, emp_code="EMP0002", email="b@b.com", department="HR"
    ))
    res = api_client.get("/employees?department=HR")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["department"] == "HR"


# --------------------------------------------------------------------------- #
# /attendance/punch-in
# --------------------------------------------------------------------------- #
def test_punch_in_unknown_employee_404(api_client):
    res = api_client.post("/attendance/punch-in", json={
        "emp_code": "EMP9999", "punched_at": PIN_MS
    })
    assert res.status_code == 404


def test_punch_in_success(api_client):
    seed_employee(api_client)
    res = seed_punch_in(api_client)
    assert res.status_code == 201
    data = res.json()
    assert data["date"] == "2026-07-06"
    assert data["late_minutes"] == 0        # 09:28 is inside grace (09:40 cutoff)
    assert data["punch_out"] is None
    assert data["work_hours"] is None
    assert data["half_day"] is False
    assert data["overtime_minutes"] == 0
    assert "_id" not in data


def test_punch_in_duplicate_409(api_client):
    seed_employee(api_client)
    seed_punch_in(api_client)
    res = api_client.post("/attendance/punch-in", json={
        "emp_code": "EMP0001",
        "punched_at": PIN_MS + 60000,   # different time, same attendance date
    })
    assert res.status_code == 409


def test_punch_in_invalid_status_422(api_client):
    seed_employee(api_client)
    # ABSENT is not a valid punch-in status
    res = api_client.post("/attendance/punch-in", json={
        "emp_code": "EMP0001", "punched_at": PIN_MS, "status": "ABSENT"
    })
    assert res.status_code == 422


def test_punch_in_late_minutes(api_client):
    seed_employee(api_client)
    # 2026-07-06 09:40:01 IST = 9*3600+40*60+1 = 34801s from midnight IST
    # IST is UTC+05:30 -> 2026-07-06 04:10:01 UTC
    late_ms = 1783311001000
    res = api_client.post("/attendance/punch-in", json={
        "emp_code": "EMP0001", "punched_at": late_ms
    })
    assert res.status_code == 201
    assert res.json()["late_minutes"] == 10   # R2: 9:40:01 -> 10 min


# --------------------------------------------------------------------------- #
# /attendance/punch-out
# --------------------------------------------------------------------------- #
def test_punch_out_success(api_client):
    seed_employee(api_client)
    seed_punch_in(api_client)
    res = api_client.post("/attendance/punch-out", json={
        "emp_code": "EMP0001", "punched_at": POUT_MS
    })
    assert res.status_code == 200
    data = res.json()
    assert data["work_hours"] == 9.12           # 9h 7m
    assert data["overtime_minutes"] == 0        # 5 min < 30 min threshold
    assert data["half_day"] is False


def test_punch_out_already_done_409(api_client):
    seed_employee(api_client)
    seed_punch_in(api_client)
    api_client.post("/attendance/punch-out", json={"emp_code": "EMP0001", "punched_at": POUT_MS})
    res = api_client.post("/attendance/punch-out", json={
        "emp_code": "EMP0001", "punched_at": POUT_MS + 10000
    })
    assert res.status_code == 409


def test_punch_out_no_punch_in_404(api_client):
    seed_employee(api_client)
    res = api_client.post("/attendance/punch-out", json={
        "emp_code": "EMP0001", "punched_at": POUT_MS
    })
    assert res.status_code == 404


def test_punch_out_before_punch_in_422(api_client):
    seed_employee(api_client)
    seed_punch_in(api_client)
    res = api_client.post("/attendance/punch-out", json={
        "emp_code": "EMP0001", "punched_at": PIN_MS - 1000  # 1 second before punch-in
    })
    assert res.status_code == 422


def test_punch_out_over_24h_422(api_client):
    seed_employee(api_client)
    seed_punch_in(api_client)
    res = api_client.post("/attendance/punch-out", json={
        "emp_code": "EMP0001", "punched_at": PIN_MS + 86401000  # 24h + 1s
    })
    assert res.status_code == 422


def test_punch_out_half_day(api_client):
    seed_employee(api_client)
    seed_punch_in(api_client)
    # 4h 28m = 4.47 hours -> half_day = True
    short_out_ms = PIN_MS + (4 * 3600 + 28 * 60) * 1000
    res = api_client.post("/attendance/punch-out", json={
        "emp_code": "EMP0001", "punched_at": short_out_ms
    })
    assert res.status_code == 200
    assert res.json()["half_day"] is True


def test_punch_out_overtime(api_client):
    seed_employee(api_client)
    seed_punch_in(api_client)
    # Punch out 30 min after shift end: 18:30 + 30 min = 19:00 IST = 13:30 UTC
    ot_out_ms = 1783344600000
    res = api_client.post("/attendance/punch-out", json={
        "emp_code": "EMP0001", "punched_at": ot_out_ms
    })
    assert res.status_code == 200
    assert res.json()["overtime_minutes"] == 30


# --------------------------------------------------------------------------- #
# GET /attendance
# --------------------------------------------------------------------------- #
def test_list_attendance_pagination_sort(api_client):
    seed_employee(api_client)
    # Create second employee on different dates
    api_client.post("/employees", json=dict(EMPLOYEE_PAYLOAD, emp_code="EMP0002", email="b@b.com"))

    seed_punch_in(api_client)
    # Punch-in for EMP0002 on a later date
    later_ms = PIN_MS + 86400000  # next day
    api_client.post("/attendance/punch-in", json={"emp_code": "EMP0002", "punched_at": later_ms})

    res = api_client.get("/attendance")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    # Should be sorted date desc: EMP0002 first (later date)
    assert data["items"][0]["emp_code"] == "EMP0002"
    assert data["items"][1]["emp_code"] == "EMP0001"


def test_list_attendance_date_from_gt_date_to_422(api_client):
    res = api_client.get("/attendance?date_from=2026-07-10&date_to=2026-07-01")
    assert res.status_code == 422


# --------------------------------------------------------------------------- #
# PATCH /attendance/{emp_code}/{date}
# --------------------------------------------------------------------------- #
def test_regularize_success(api_client):
    seed_employee(api_client)
    seed_punch_in(api_client)
    res = api_client.patch("/attendance/EMP0001/2026-07-06", json={
        "status": "WFH",
        "reason": "Traffic jam blocked road",
        "regularized_by": "Manager Bob",
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "WFH"
    assert len(data["history"]) == 1
    hist = data["history"][0]
    assert hist["by"] == "Manager Bob"
    assert "status" in hist["changes"]
    assert hist["changes"]["status"] == {"from": "PRESENT", "to": "WFH"}


def test_regularize_no_change_422(api_client):
    seed_employee(api_client)
    seed_punch_in(api_client)
    # WFH
    api_client.patch("/attendance/EMP0001/2026-07-06", json={
        "status": "WFH", "reason": "Traffic issue here", "regularized_by": "Boss"
    })
    # Sending the same status again (no actual change)
    res = api_client.patch("/attendance/EMP0001/2026-07-06", json={
        "status": "WFH", "reason": "Trying again same update", "regularized_by": "Boss"
    })
    assert res.status_code == 422


def test_regularize_absent_with_punch_time_422(api_client):
    seed_employee(api_client)
    seed_punch_in(api_client)
    res = api_client.patch("/attendance/EMP0001/2026-07-06", json={
        "status": "ABSENT",
        "punch_in": PIN_MS,
        "reason": "Override attendance record",
        "regularized_by": "HR",
    })
    assert res.status_code == 422


def test_regularize_employee_not_found_404(api_client):
    res = api_client.patch("/attendance/EMP9999/2026-07-06", json={
        "reason": "Testing not found case", "regularized_by": "HR"
    })
    assert res.status_code == 404


def test_regularize_record_not_found_404(api_client):
    seed_employee(api_client)
    res = api_client.patch("/attendance/EMP0001/2026-07-06", json={
        "reason": "Testing no record case", "regularized_by": "HR"
    })
    assert res.status_code == 404


def test_regularize_history_appends_multiple(api_client):
    """Each regularization appends exactly one history entry."""
    seed_employee(api_client)
    seed_punch_in(api_client)
    api_client.patch("/attendance/EMP0001/2026-07-06", json={
        "status": "WFH", "reason": "First change ever made", "regularized_by": "HR"
    })
    api_client.patch("/attendance/EMP0001/2026-07-06", json={
        "status": "ON_DUTY", "reason": "Second change ever made", "regularized_by": "Manager"
    })
    res = api_client.get("/attendance?emp_code=EMP0001")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items[0]["history"]) == 2
