# Employee Attendance & Analytics API

FastAPI and MongoDB backend service implementing employee attendance management, business rules (R1-R10), manual audit corrections, and MongoDB aggregation analytics.

## Requirements
- Python 3.11+
- MongoDB 6.0+ (Atlas free tier M0 or local container)

## Setup & Running

1. **Create and activate a virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate       # On Windows: .venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment:**
   Set `MONGO_URI` and `MONGO_DB` via environment variables (or a local `.env`):
   ```bash
   export MONGO_URI="mongodb://localhost:27017"
   export MONGO_DB="attendance_db"
   ```

4. **Start the API:**
   ```bash
   uvicorn app.main:app --port 8000
   ```
   The application initializes all required MongoDB indexes at startup via a lifespan handler.

## Overview
- `app/main.py`: Complete application containing models, business rules, concurrency handling, and aggregation analytics.
- `REVIEW.md`: Detailed defect analysis and fixes identified in the starter code.
- `DECISIONS.md`: Architectural decisions regarding indexing, concurrency, ties, headcount, and horizontal scalability.
