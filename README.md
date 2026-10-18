# QueryMind — AI-Powered Natural Language to MySQL Assistant

QueryMind lets you ask questions about an e-commerce database in plain
English. It uses Google Gemini to generate MySQL-compatible SQL, validates
the query for safety with SQLGlot, executes read-only queries against a
real MySQL database, and presents the results with a plain-English
explanation.

The application never fabricates database results and never executes
model-generated SQL without validation.

## Project structure

```
querymind/
├── app.py                  # Streamlit frontend
├── database.py             # SQLAlchemy connection, introspection, read-only execution
├── ai_engine.py            # Gemini natural-language → SQL generation
├── sql_safety.py           # SQLGlot-based read-only validation
├── query_templates.py      # Deterministic SQL templates for common questions
├── clarification.py        # Deterministic ambiguity detection
├── init_db.py              # Idempotent MySQL schema + sample-data initialization
├── requirements.txt        # Python dependencies
├── .env.example            # Environment variable placeholders
├── .gitignore              # Excludes secrets, caches, virtualenvs
├── README.md               # This file
└── tests/
    ├── conftest.py         # Pytest fixtures (MySQL availability, URLs)
    ├── test_sql_safety.py  # SELECT acceptance, mutation/DDL rejection
    ├── test_clarification.py
    ├── test_database.py    # Unit + guarded MySQL integration tests
    ├── test_ai_engine.py   # Mocked Gemini tests
    └── test_templates.py
```

## Technology stack

- Python 3.12+ (developed/tested on Python 3.13)
- Streamlit — frontend
- MySQL 8.0 — primary database
- SQLAlchemy + PyMySQL — database connectivity
- Google Gemini (official `google-genai` SDK) — AI SQL generation
- SQLGlot — MySQL SQL parsing and validation
- python-dotenv — environment configuration
- pytest — automated tests

SQLite is **not** used as the primary database.

## Stage 1 findings (environment)

- Workspace: empty
- Python: 3.13.15 (`venv` available)
- MySQL: 8.0.46 installed, `MySQL80` service running
- Root MySQL login requires a password (not provided; see setup below)
- Pre-installed: PyMySQL 1.2.0, SQLAlchemy 2.0.52

## Windows setup (PowerShell)

### 1. Create and activate a virtual environment

```powershell
cd C:\Users\amtec\OneDrive\Desktop\mlh\New folder\querymind
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Configure environment

```powershell
copy .env.example .env
# Edit .env and set GEMINI_API_KEY and DB_PASSWORD (never commit .env)
notepad .env
```

`.env.example` contains:

```
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.8-flash
DB_HOST=localhost
DB_PORT=3306
DB_NAME=querymind_db
DB_USER=querymind_app
DB_PASSWORD=
```

Get a Gemini API key from [Google AI Studio](https://aistudio.google.com/).

### 4. Create the MySQL database and restricted user

You need MySQL admin (root) credentials. The app connects as a restricted
`querymind_app` user with **SELECT only** on `querymind_db.*`.

Do not run destructive commands. Initialize idempotently:

```powershell
# Set your MySQL root password and an app password
$env:MYSQL_ROOT_PASSWORD="<your-root-password>"
$env:DB_PASSWORD="<choose-app-password>"

python - <<'PY'
from init_db import initialize
admin_url = "mysql+pymysql://root:<root-password>@localhost:3306/"
initialize(admin_url, "<choose-app-password>")
print("Initialization complete.")
PY
```

Or review and run the equivalent SQL manually. `init_db.py` uses
`CREATE DATABASE IF NOT EXISTS`, `CREATE USER IF NOT EXISTS`, `CREATE
TABLE IF NOT EXISTS`, and seeds data only into empty tables. It **never
drops or truncates**.

### 5. Run tests

```powershell
# Unit tests (no MySQL or API key needed)
pytest

# Integration tests (require MySQL admin credentials)
$env:MYSQL_ROOT_PASSWORD="<your-root-password>"
$env:MYSQL_ROOT_USER="root"
pytest tests/test_database.py -m integration -v
```

Unit-test results are separate from MySQL integration-test results;
integration tests are skipped when MySQL is unreachable.

### 6. Launch the application

```powershell
streamlit run app.py
```

Open the URL Streamlit prints (typically `http://localhost:8501`).

## How it works

1. You type a natural-language question (e.g. "Which five products
   generated the highest sales?").
2. QueryMind introspects the live MySQL schema.
3. A deterministic clarification check runs first; genuinely ambiguous
   requests ("best customers", "revenue") prompt a clarification question.
4. A matching SQL template is tried; otherwise Gemini generates SQL.
5. SQLGlot validates the query: single read-only SELECT only, allowlisted
   tables, no system schemas, result limits enforced.
6. The validated query executes against MySQL via a restricted app user.
7. Results display in an interactive table with a plain-English
   explanation and a chart only when the data supports one.

## Example questions

- "Which five products generated the highest sales?"
- "How many customers are there in total?"
- "Show recent orders from the last 30 days."
- "What is the sales breakdown by product category?"
- "How many orders are there by status?"
- "Which customers have the highest total completed purchases?"

## Security

- Database credentials and API keys are loaded from `.env` and **never**
  printed, logged, or shown in the UI.
- Model-generated SQL is validated by SQLGlot before execution; it is
  never executed directly.
- The app uses a dedicated MySQL user with SELECT-only privileges.
- Read-only sessions, statement timeouts, and bounded result sets are
  applied where the server supports them.
- SQLGlot is a validation aid, not a complete security boundary; defense
  in depth is used.

## Streamlit Community Cloud deployment

The app uses a local MySQL database. For public deployment you need a
reachable, securely configured MySQL-compatible database service (e.g.
Amazon RDS, Azure Database for MySQL, Google Cloud SQL, or a managed
provider) with network access from Streamlit Community Cloud.

**Do not expose a local MySQL instance directly to the public internet.**

Set the same environment variables in Streamlit Community Cloud's
settings/secrets. Deployment is not considered complete until it has been
deployed and verified end-to-end.

## Required environment variables

| Variable | Description |
|---|---|
| GEMINI_API_KEY | Google Gemini API key |
| GEMINI_MODEL | Gemini model (default: gemini-3.8-flash) |
| DB_HOST | MySQL host (default: localhost) |
| DB_PORT | MySQL port (default: 3306) |
| DB_NAME | Database name (default: querymind_db) |
| DB_USER | App database user (default: querymind_app) |
| DB_PASSWORD | App database user password |

## Publishing without secrets

1. Never commit `.env`.
2. `.gitignore` excludes `.env`, `.venv/`, `__pycache__/`, and IDE files.
3. Copy `.env.example` to `.env` locally and fill in values.
4. On Streamlit Community Cloud, add secrets through the UI settings.

## License

Hackathon project. Internal use.
