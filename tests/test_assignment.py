import pytest
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal
from pydantic import ValidationError

from app.main import (
    IST,
    round_half_up,
    epoch_ms_to_datetime,
    datetime_to_epoch_ms,
    calculate_attendance_date,
    compute_late_minutes,
    compute_overtime,
    compute_work_hours,
    compute_half_day,
    count_working_days,
    EmployeeCreate,
    PunchInRequest,
    RegularizeRequest,
)


def test_round_half_up():
    assert round_half_up(9.125, 2) == 9.13
    assert round_half_up(9.124, 2) == 9.12
    assert round_half_up(0.12345, 4) == 0.1235
    assert round_half_up(0.12344, 4) == 0.1234
    assert round_half_up(None) is None


def test_r1_instant_truncation():
    # 09:40:00.900 should truncate to 09:40:00.000
    ms = 1783312800900
    dt = epoch_ms_to_datetime(ms)
    assert dt.microsecond == 0
    assert datetime_to_epoch_ms(dt) == 1783312800000


def test_r1_overnight_shift_date():
    # Regular day shift 09:30 to 18:30
    dt_day = datetime(2026, 7, 6, 9, 28, 0, tzinfo=IST).astimezone(timezone.utc)
    assert calculate_attendance_date(dt_day, "09:30", "18:30") == "2026-07-06"

    # Overnight shift 22:00 to 06:00
    # Punch-in at 05:30 on 2026-07-07 (< 06:00) belongs to 2026-07-06
    dt_early = datetime(2026, 7, 7, 5, 30, 0, tzinfo=IST).astimezone(timezone.utc)
    assert calculate_attendance_date(dt_early, "22:00", "06:00") == "2026-07-06"

    # Punch-in at 22:05 on 2026-07-06 belongs to 2026-07-06
    dt_night = datetime(2026, 7, 6, 22, 5, 0, tzinfo=IST).astimezone(timezone.utc)
    assert calculate_attendance_date(dt_night, "22:00", "06:00") == "2026-07-06"


def test_r2_late_minutes():
    # Shift 09:30: 09:40:00 -> 0; 09:40:01 -> 10; 10:15:59 -> 45
    t0 = datetime(2026, 7, 6, 9, 40, 0, tzinfo=IST).astimezone(timezone.utc)
    assert compute_late_minutes(t0, "09:30", "2026-07-06") == 0

    t1 = datetime(2026, 7, 6, 9, 40, 1, tzinfo=IST).astimezone(timezone.utc)
    assert compute_late_minutes(t1, "09:30", "2026-07-06") == 10

    t2 = datetime(2026, 7, 6, 10, 15, 59, tzinfo=IST).astimezone(timezone.utc)
    assert compute_late_minutes(t2, "09:30", "2026-07-06") == 45


def test_r3_overtime_minutes():
    # Shift end 18:30
    # 18:59:00 -> 29 min -> 0
    t_29 = datetime(2026, 7, 6, 18, 59, 0, tzinfo=IST).astimezone(timezone.utc)
    assert compute_overtime(t_29, "18:30", "09:30", "2026-07-06") == 0

    # 19:00:00 -> 30 min -> 30
    t_30 = datetime(2026, 7, 6, 19, 0, 0, tzinfo=IST).astimezone(timezone.utc)
    assert compute_overtime(t_30, "18:30", "09:30", "2026-07-06") == 30

    # Overnight shift 22:00 to 06:00
    # Punch out 06:45 on next calendar day -> 45 min
    t_ot_night = datetime(2026, 7, 7, 6, 45, 0, tzinfo=IST).astimezone(timezone.utc)
    assert compute_overtime(t_ot_night, "06:00", "22:00", "2026-07-06") == 45


def test_r4_work_hours_and_r5_half_day():
    pin = datetime(2026, 7, 6, 9, 0, 0, tzinfo=IST).astimezone(timezone.utc)
    pout = datetime(2026, 7, 6, 13, 29, 0, tzinfo=IST).astimezone(timezone.utc)
    # 4h 29m = 4.48 hours -> half_day = True
    wh = compute_work_hours(pin, pout)
    assert wh == 4.48
    assert compute_half_day(wh) is True

    pout2 = datetime(2026, 7, 6, 13, 30, 0, tzinfo=IST).astimezone(timezone.utc)
    # 4h 30m = 4.50 hours -> half_day = False
    wh2 = compute_work_hours(pin, pout2)
    assert wh2 == 4.50
    assert compute_half_day(wh2) is False


def test_r7_working_days():
    # July 2026 has 23 Mon-Fri days for someone who joined on or before July 1
    assert count_working_days("2026-07", "2026-01-05") == 23

    # Mid-month joiner: joined July 15, 2026 (Wed)
    # July 15, 16, 17 = 3 days; July 20-24 = 5 days; July 27-31 = 5 days -> Total 13 days
    assert count_working_days("2026-07", "2026-07-15") == 13

    # Joined in next month
    assert count_working_days("2026-07", "2026-08-01") == 0


def test_employee_validation():
    # Valid
    emp = EmployeeCreate(
        emp_code="EMP0001",
        name="Asha Rao",
        email="asha@example.com",
        department="Engineering",
        shift_start="09:30",
        shift_end="18:30",
        joined_on="2026-01-05",
    )
    assert emp.emp_code == "EMP0001"

    # shift_start == shift_end must fail
    with pytest.raises(ValidationError):
        EmployeeCreate(
            emp_code="EMP0002",
            name="Bob",
            email="bob@example.com",
            department="QA",
            shift_start="09:30",
            shift_end="09:30",
            joined_on="2026-01-05",
        )

    # Invalid emp_code pattern
    with pytest.raises(ValidationError):
        EmployeeCreate(
            emp_code="INVALID123",
            name="Charlie",
            email="charlie@example.com",
            department="HR",
            joined_on="2026-01-05",
        )
