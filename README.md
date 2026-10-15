# Employee Attendance & Analytics API

FastAPI and MongoDB service for employee attendance, audit corrections, and analytics.

## Requirements

- Python 3.11 or newer
- MongoDB 6.0 or newer

## Run on Windows

From PowerShell at the repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
$env:MONGO_URI = "mongodb://localhost:27017"
$env:MONGO_DB = "attendance_db"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Start MongoDB before starting the API. The application creates its indexes at startup and fails to start if MongoDB is
unavailable or index creation fails.

Open `http://127.0.0.1:8000/docs` for the interactive API documentation. Check readiness at
`http://127.0.0.1:8000/health`. Stop the server with `Ctrl+C`.

To load the sample records, set a separate development database name and run:

```powershell
$env:MONGO_DB = "attendance_db_demo"
.\.venv\Scripts\python.exe .\sample_seed.py
```

The seed script replaces all documents in the `employees` and `attendance_logs` collections of the selected database.
Do not point it at data you need to keep.

## Tests

Install the test dependencies and run the unit/API tests:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\requirements-dev.txt
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe -m pytest -q
```

The mock tests run without a live database. To additionally run integration checks against MongoDB, set
`TEST_MONGO_URI` to a disposable local or test MongoDB instance before running pytest:

```powershell
$env:TEST_MONGO_URI = "mongodb://localhost:27017"
.\.venv\Scripts\python.exe -m pytest -q
Remove-Item Env:TEST_MONGO_URI
```

Integration tests load only the included sample data into a uniquely named temporary database and drop that database
after the test.

## Project files

- `app/main.py` — API endpoints, validation, business rules, aggregation pipelines, and index setup.
- `openapi.yaml` — HTTP contract and rules R1–R10.
- `DATA_MODEL.md` — MongoDB document shapes and sample data.
- `REVIEW.md` — Starter-code defect review and fixes.
- `DECISIONS.md` — Design and scaling decisions.
- `tests/` — Unit, mock API, and optional MongoDB integration tests.
