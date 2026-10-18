"""QueryMind — AI-Powered Natural Language to MySQL Assistant.

Streamlit frontend. Never prints or exposes API keys, database passwords,
or internal stack traces to the user.
"""

from __future__ import annotations

import os
import traceback
from typing import Any
from urllib.parse import quote_plus

import streamlit as st

from ai_engine import AIEngine, OPENROUTER_FREE_MODELS, OLLAMA_FREE_MODELS
from clarification import ClarificationEngine
from database import ALLOWED_TABLES, Database, DatabaseError
from query_templates import list_templates, match_template
from sql_safety import DEFAULT_MAX_RESULT_COUNT, SqlSafetyValidator

PAGE_TITLE = "QueryMind"
PAGE_ICON = "🧠"

EXAMPLE_QUESTIONS = [
    "Which five products generated the highest sales?",
    "How many customers are there in total?",
    "Show recent orders from the last 30 days.",
    "What is the sales breakdown by product category?",
    "How many orders are there by status?",
    "Which customers have the highest total completed purchases?",
    "Show me the best customers.",  # ambiguous -> clarification
    "Show me recent revenue.",  # ambiguous -> clarification
]


def init_session_state() -> None:
    if "history" not in st.session_state:
        st.session_state.history: list[dict[str, Any]] = []
    if "current" not in st.session_state:
        st.session_state.current: dict[str, Any] | None = None
    if "clarification_pending" not in st.session_state:
        st.session_state.clarification_pending = False
    if "db" not in st.session_state:
        st.session_state.db = Database()
    if "safety" not in st.session_state:
        st.session_state.safety = SqlSafetyValidator()
    if "clarifier" not in st.session_state:
        st.session_state.clarifier = ClarificationEngine()
    if "ai" not in st.session_state:
        st.session_state.ai = AIEngine()
    if "available_databases" not in st.session_state:
        st.session_state.available_databases: list[str] = []
    if "db_admin_url" not in st.session_state:
        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "3306")
        user = quote_plus(os.getenv("DB_ADMIN_USER", "root"))
        password = quote_plus(os.getenv("DB_ADMIN_PASSWORD", ""))
        st.session_state.db_admin_url = (
            f"mysql+pymysql://{user}:{password}@{host}:{port}/"
        )


def safe_error(exc: Exception) -> str:
    """Return a user-safe error message (no stack traces, no secrets)."""
    _ = traceback.format_exc()  # logged server-side only, never shown
    msg = str(exc).strip()
    if not msg:
        msg = type(exc).__name__
    # Never surface raw connection strings or passwords.
    for token in ("mysql+pymysql://", "@", "DB_PASSWORD", "GEMINI_API_KEY"):
        msg = msg.replace(token, "[redacted]")
    return f"{type(exc).__name__}: {msg}"


def render_sidebar(db: Database, ai: AIEngine) -> None:
    st.sidebar.title(PAGE_TITLE)
    st.sidebar.caption("Natural Language → MySQL")

    # Database connection status
    st.sidebar.subheader("Database Status")
    health = db.health_check()
    if health.get("healthy"):
        st.sidebar.success("Connected to MySQL")
        st.sidebar.caption(f"Database: {health.get('database')}")
        st.sidebar.caption(f"Version: {health.get('version')}")
    else:
        st.sidebar.error("Database not connected")
        st.sidebar.caption(health.get("message", "Unknown error"))
        st.sidebar.caption("Configure .env and confirm MySQL is running.")

    # Database switcher
    st.sidebar.caption("Switch database:")
    db_cols = st.sidebar.columns([3, 1])
    new_db = db_cols[0].text_input(
        "Database name",
        value=health.get("database") or os.getenv("DB_NAME", "querymind_db"),
        key="db_switch_input",
        label_visibility="collapsed",
    )
    if db_cols[1].button("Switch", key="db_switch", use_container_width=True):
        if new_db and new_db != (health.get("database") or ""):
            try:
                db.switch_database(new_db)
                st.sidebar.success(f"Switched to {new_db}")
                st.rerun()
            except Exception as exc:
                st.sidebar.error(f"Switch failed: {safe_error(exc)}")

    # List available databases (needs admin creds)
    admin_url = st.session_state.db_admin_url
    if admin_url and not st.session_state.available_databases:
        dbs = Database.list_databases(admin_url)
        st.session_state.available_databases = dbs
    if st.session_state.available_databases:
        st.sidebar.caption("Available databases:")
        for dbname in st.session_state.available_databases:
            if st.sidebar.button(
                dbname, key=f"db_list_{dbname}", use_container_width=True
            ):
                try:
                    db.switch_database(dbname)
                    st.sidebar.success(f"Switched to {dbname}")
                    st.rerun()
                except Exception as exc:
                    st.sidebar.error(f"Switch failed: {safe_error(exc)}")

    st.sidebar.divider()

    # AI status
    st.sidebar.subheader("AI (Gemini / OpenRouter / Ollama / OpenCode)")
    ai: AIEngine = st.session_state.ai
    if ai.available:
        st.sidebar.success(f"AI configured: {ai.provider}")
        st.sidebar.caption(f"Model: {ai.model_name}")
    else:
        st.sidebar.warning("AI not configured")
        st.sidebar.caption(ai.init_error() or "No provider available")
        st.sidebar.caption("Template queries still work.")

    # Provider switcher
    st.sidebar.caption("Switch provider:")
    prov_cols = st.sidebar.columns(4)
    if prov_cols[0].button("Gemini", key="ai_gemini", use_container_width=True):
        st.session_state.ai = AIEngine(provider="gemini")
        st.rerun()
    if prov_cols[1].button("OpenRouter", key="ai_openrouter", use_container_width=True):
        st.session_state.ai = AIEngine(provider="openrouter")
        st.rerun()
    if prov_cols[2].button("Ollama", key="ai_ollama", use_container_width=True):
        st.session_state.ai = AIEngine(provider="ollama")
        st.rerun()
    if prov_cols[3].button("OpenCode", key="ai_openai", use_container_width=True):
        st.session_state.ai = AIEngine(provider="openai")
        st.rerun()

    st.sidebar.divider()

    # Example questions
    st.sidebar.subheader("Example questions")
    for idx, q in enumerate(EXAMPLE_QUESTIONS):
        if st.sidebar.button(q, key=f"example_q_{idx}", use_container_width=True):
            st.session_state.pending_question = q

    st.sidebar.divider()

    # Schema explorer
    st.sidebar.subheader("Schema explorer")
    try:
        schema = db.get_schema()
    except Exception:
        schema = {}
    if schema:
        for table in sorted(schema):
            with st.sidebar.expander(table, expanded=False):
                cols = schema[table].get("columns", [])
                for col in cols:
                    nullable = "NULL" if col.get("nullable") else "NOT NULL"
                    st.caption(
                        f"`{col['name']}` {col['type']} ({nullable})"
                    )
                pks = schema[table].get("primary_keys", [])
                if pks:
                    st.caption(f"PK: {', '.join(pks)}")
                fks = schema[table].get("foreign_keys", [])
                for fk in fks:
                    st.caption(
                        f"FK: {', '.join(fk.get('columns', []))} → "
                        f"{fk.get('referred_table')}"
                        f"({', '.join(fk.get('referred_columns', []))})"
                    )
    else:
        st.sidebar.caption("Schema unavailable (connect to MySQL).")

    st.sidebar.divider()
    st.sidebar.caption("Allowed tables: " + ", ".join(sorted(ALLOWED_TABLES)))


def render_history() -> None:
    st.subheader("Query history (this session)")
    if not st.session_state.history:
        st.caption("No queries yet.")
        return
    for i, entry in enumerate(reversed(st.session_state.history)):
        with st.expander(
            f"Q{len(st.session_state.history) - i}: {entry['question'][:60]}",
            expanded=False,
        ):
            st.code(entry.get("sql", ""), language="sql")
            if entry.get("explanation"):
                st.caption(entry["explanation"])
            rows = entry.get("rows", [])
            st.caption(f"Rows returned: {len(rows)}")
            if rows:
                st.dataframe(rows, use_container_width=True, hide_index=True)


def try_render_chart(rows: list[dict[str, Any]]) -> bool:
    """Render a simple chart only when the data clearly supports it.

    Returns True if a chart was rendered.
    """
    if not rows or len(rows) < 2:
        return False
    try:
        import plotly.express as px  # type: ignore
        import pandas as pd
    except Exception:
        return False

    keys = list(rows[0].keys())
    numeric_keys = [
        k for k in keys
        if all(isinstance(r.get(k), (int, float)) and r.get(k) is not None
               for r in rows)
    ]
    text_keys = [
        k for k in keys
        if all(isinstance(r.get(k), str) for r in rows)
    ]
    if not numeric_keys or not text_keys:
        return False

    x_key = text_keys[0]
    y_key = numeric_keys[0]
    df = pd.DataFrame(rows)
    fig = px.bar(df, x=x_key, y=y_key, title=f"{y_key} by {x_key}")
    st.plotly_chart(fig, use_container_width=True)
    return True


def handle_question(question: str, db: Database, safety: SqlSafetyValidator,
                    clarifier: ClarificationEngine, ai: AIEngine) -> None:
    """Run the full question pipeline and store the result in session state."""
    result: dict[str, Any] = {
        "question": question,
        "sql": None,
        "explanation": None,
        "rows": [],
        "error": None,
        "clarification": None,
    }

    try:
        # 1. Clarification check
        clarification = clarifier.assess(question)
        if clarification.needed:
            result["clarification"] = clarification
            st.session_state.current = result
            st.session_state.history.append(result)
            return

        # 2. Deterministic template first
        template = match_template(question)
        sql = None
        if template is not None:
            sql = template.sql
            result["explanation"] = (
                f"Used template '{template.name}': {template.description}"
            )
        else:
            # 3. AI fallback
            schema = db.get_schema()
            gen = ai.generate(question, schema)
            if gen.error:
                result["error"] = gen.error
                st.session_state.current = result
                st.session_state.history.append(result)
                return
            if gen.clarification_needed and gen.clarification_question:
                result["clarification"] = Clarification(
                    needed=True,
                    question=gen.clarification_question,
                    reason="AI flagged ambiguous request.",
                )
                st.session_state.current = result
                st.session_state.history.append(result)
                return
            sql = gen.sql
            result["explanation"] = gen.explanation or "Generated by AI."

        if not sql:
            result["error"] = "No SQL could be generated for this question."
            st.session_state.current = result
            st.session_state.history.append(result)
            return

        # 4. Safety validation
        safety_result = safety.validate(sql)
        if not safety_result.safe:
            result["error"] = (
                "Query rejected by safety validation: "
                + "; ".join(safety_result.errors)
            )
            result["sql"] = sql
            st.session_state.current = result
            st.session_state.history.append(result)
            return

        # 5. Execute
        rows = db.execute_readonly(safety_result.sql or sql)
        result["sql"] = safety_result.sql or sql
        result["rows"] = rows
        if not rows:
            result["explanation"] = (
                (result["explanation"] or "") +
                " The query returned no rows."
            ).strip()

    except DatabaseError as exc:
        result["error"] = safe_error(exc)
    except Exception as exc:  # noqa: BLE001 - UI boundary
        result["error"] = safe_error(exc)

    st.session_state.current = result
    st.session_state.history.append(result)


def render_current(db: Database) -> None:
    st.subheader("Results")

    if st.session_state.clarification_pending:
        st.info("A clarification is pending. Please rephrase your question.")

    current = st.session_state.current
    if current is None:
        st.caption("Ask a question to get started.")
        return

    # Clarification message
    if current.get("clarification"):
        clar = current["clarification"]
        st.warning("Clarification needed")
        st.write(clar.get("question") or "Could you clarify your request?")
        return

    # Error
    if current.get("error"):
        st.error(current["error"])
        if current.get("sql"):
            st.code(current["sql"], language="sql")
        return

    # SQL
    if current.get("sql"):
        st.code(current["sql"], language="sql")

    # Explanation
    if current.get("explanation"):
        st.info(current["explanation"])

    # Results table
    rows = current.get("rows", [])
    if rows:
        st.caption(f"Rows returned: {len(rows)}")
        st.dataframe(rows, use_container_width=True, hide_index=True)
        try_render_chart(rows)
    else:
        if not current.get("error") and not current.get("clarification"):
            st.caption("No rows returned.")


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON, layout="wide")
    init_session_state()

    db: Database = st.session_state.db
    safety: SqlSafetyValidator = st.session_state.safety
    clarifier: ClarificationEngine = st.session_state.clarifier
    ai: AIEngine = st.session_state.ai

    st.title(f"{PAGE_ICON} {PAGE_TITLE}")
    st.caption(
        "Ask questions about the e-commerce database in plain English. "
        "QueryMind generates, validates, and executes safe read-only SQL."
    )

    render_sidebar(db, ai)

    # Pending question from example-button click
    pending = st.session_state.pop("pending_question", None)

    with st.form("question_form", clear_on_submit=False):
        question = st.text_input(
            "Your question",
            value=pending or "",
            placeholder="e.g. Which five products generated the highest sales?",
        )
        col_ask, col_clear = st.columns([1, 1])
        ask = col_ask.form_submit_button("Ask", type="primary")
        clear = col_clear.form_submit_button("Clear")

    if clear:
        st.session_state.current = None
        st.session_state.clarification_pending = False
        st.session_state.history = []
        st.rerun()

    if ask and question.strip():
        handle_question(question.strip(), db, safety, clarifier, ai)

    render_current(db)

    st.divider()
    render_history()


if __name__ == "__main__":
    main()
