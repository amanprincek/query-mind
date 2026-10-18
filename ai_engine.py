"""AI engine for natural-language to MySQL SQL generation.

Supports multiple free/low-cost model providers:
- Google Gemini (official SDK) — default
- OpenRouter — access to many free models (OpenCode, Llama, etc.)
- Ollama — local free models

Generated SQL is NEVER executed directly; it is returned for safety
validation and execution.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

load_dotenv()

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"

# OpenRouter free models (OpenCode-style and others).
OPENROUTER_FREE_MODELS = [
    "openrouter/auto",
    "meta-llama/llama-3.1-8b-instruct:free",
    "google/gemma-2-9b-it:free",
    "microsoft/phi-3-mini-128k-instruct:free",
    "nvidia/nemotron-3-1-super-49b-v1:free",
]

# OpenCode-compatible models via NVIDIA API Catalog / OpenAI-compatible endpoints.
# Nemotron 3.5 Super VL Free and similar models are available through
# OpenAI-compatible APIs (e.g., https://integrate.api.nvidia.com/v1).
OPENCODE_FREE_MODELS = [
    "nemotron-3.5-super-vl-free",
    "nemotron-3.5-super-49b-v1",
    "llama-3.1-nemotron-ultra-253b-v1",
]

# OpenAI-compatible endpoint defaults for popular providers.
OPENAI_COMPATIBLE_PROVIDERS = {
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "together": "https://api.together.xyz/v1",
    "groq": "https://api.groq.com/openai/v1",
}

# Ollama local free models.
OLLAMA_FREE_MODELS = [
    "llama3.1:8b",
    "gemma2:9b",
    "phi3:mini",
    "qwen2.5:7b",
]


@dataclass
class GenerationResult:
    clarification_needed: bool
    clarification_question: str | None
    sql: str | None
    explanation: str | None
    raw: str | None = None
    error: str | None = None
    provider: str | None = None
    model: str | None = None


class AIEngine:
    """Multi-provider AI engine for natural-language → SQL generation.

    Tries Gemini first, then falls back to OpenRouter or Ollama if
    configured. Never executes SQL directly.
    """

    def __init__(
        self,
        provider: str | None = None,
        model_name: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.provider = provider or os.getenv("AI_PROVIDER", "gemini")
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.openai_base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL", "")
        self.openai_api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY", "")

        # Resolve model name.
        if model_name:
            self.model_name = model_name
        elif self.provider == "openrouter":
            self.model_name = os.getenv("OPENROUTER_MODEL", OPENROUTER_FREE_MODELS[0])
        elif self.provider == "ollama":
            self.model_name = os.getenv("OLLAMA_MODEL", OLLAMA_FREE_MODELS[0])
        elif self.provider == "openai":
            self.model_name = model_name or os.getenv(
                "OPENAI_COMPATIBLE_MODEL", OPENCODE_FREE_MODELS[0]
            )
        else:
            self.model_name = model_name or os.getenv(
                "GEMINI_MODEL", DEFAULT_GEMINI_MODEL
            )

        self.base_url = base_url or self.openai_base_url or os.getenv("AI_BASE_URL", "")

        self._client: Any = None
        self._available = False
        self._init_error: str | None = None
        self._initialize()

    # ------------------------------------------------------------------ #
    # Initialization
    # ------------------------------------------------------------------ #
    def _initialize(self) -> None:
        if self.provider == "gemini":
            self._init_gemini()
        elif self.provider == "openrouter":
            self._init_openrouter()
        elif self.provider == "ollama":
            self._init_ollama()
        elif self.provider == "openai":
            self._init_openai_compatible()
        else:
            self._init_error = (
                f"Unknown AI provider '{self.provider}'. "
                f"Use 'gemini', 'openrouter', 'ollama', or 'openai'."
            )

    def _init_gemini(self) -> None:
        if not self.api_key:
            self._init_error = (
                "GEMINI_API_KEY is not set. AI SQL generation is disabled. "
                "Template-based queries remain usable."
            )
            return

        try:
            from google import genai  # type: ignore
        except ImportError as exc:  # pragma: no cover - environment issue
            self._init_error = (
                "google-genai SDK is not installed. AI SQL generation "
                f"is disabled. ({exc})"
            )
            return

        self._client = genai.Client(
            api_key=self.api_key,
            http_options=genai.types.HttpOptions(
                timeout=60_000,
                retry_options=genai.types.HttpRetryOptions(attempts=1),
            ),
        )
        self._available = True
        self._init_error = None

    def _init_openrouter(self) -> None:
        if not self.openrouter_key:
            self._init_error = (
                "OPENROUTER_API_KEY is not set. OpenRouter AI is disabled. "
                "Get a free key at https://openrouter.ai/"
            )
            return

        try:
            import requests  # type: ignore
        except ImportError as exc:  # pragma: no cover
            self._init_error = (
                "requests package is required for OpenRouter. "
                f"Install it. ({exc})"
            )
            return

        self._client = requests
        self._available = True

    def _init_ollama(self) -> None:
        try:
            import requests  # type: ignore
        except ImportError as exc:  # pragma: no cover
            self._init_error = (
                "requests package is required for Ollama. "
                f"Install it. ({exc})"
            )
            return

        self._client = requests
        # Ollama availability is checked at request time (server may be down).
        self._available = True

    def _init_openai_compatible(self) -> None:
        """Initialize an OpenAI-compatible provider (NVIDIA, OpenRouter, etc.) for OpenCode models."""
        # Prefer the dedicated OpenAI-compatible API key, fall back to Gemini key.
        key = self.openai_api_key or self.api_key
        if not key:
            self._init_error = (
                "OPENAI_COMPATIBLE_API_KEY (or GEMINI_API_KEY) is not set. "
                "OpenAI-compatible AI is disabled. "
                "Get a free key from NVIDIA API Catalog (build.nvidia.com) "
                "or OpenRouter (openrouter.ai)."
            )
            return

        if not self.base_url:
            self._init_error = (
                "OPENAI_COMPATIBLE_BASE_URL is not set. "
                "Example: https://integrate.api.nvidia.com/v1 for NVIDIA Nemotron models."
            )
            return

        try:
            import requests  # type: ignore
        except ImportError as exc:  # pragma: no cover
            self._init_error = (
                "requests package is required for OpenAI-compatible provider. "
                f"Install it. ({exc})"
            )
            return

        self._client = requests
        self._available = True

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    @property
    def available(self) -> bool:
        return self._available

    def init_error(self) -> str | None:
        return self._init_error

    def generate(self, question: str, schema: dict) -> GenerationResult:
        """Generate a structured SQL response for ``question``.

        Never executes SQL. Returns a :class:`GenerationResult`.
        """
        if not self._available:
            return GenerationResult(
                clarification_needed=False,
                clarification_question=None,
                sql=None,
                explanation=None,
                error=self._init_error or "AI engine is not available.",
                provider=self.provider,
                model=self.model_name,
            )

        prompt = self._build_prompt(question, schema)

        try:
            if self.provider == "gemini":
                return self._generate_gemini(prompt, question)
            if self.provider == "openrouter":
                return self._generate_openrouter(prompt, question)
            if self.provider == "ollama":
                return self._generate_ollama(prompt, question)
            if self.provider == "openai":
                return self._generate_openai_compatible(prompt, question)
        except Exception as exc:  # noqa: BLE001 - provider errors
            return GenerationResult(
                clarification_needed=False,
                clarification_question=None,
                sql=None,
                explanation=None,
                raw=None,
                error=f"AI request failed ({self.provider}): {type(exc).__name__}",
                provider=self.provider,
                model=self.model_name,
            )

        return GenerationResult(
            clarification_needed=False,
            clarification_question=None,
            sql=None,
            explanation=None,
            error=f"Unknown provider '{self.provider}'.",
            provider=self.provider,
            model=self.model_name,
        )

    # ------------------------------------------------------------------ #
    # Provider implementations
    # ------------------------------------------------------------------ #
    def _generate_gemini(
        self, prompt: str, question: str
    ) -> GenerationResult:
        assert self._client is not None
        try:
            response = self._client.interactions.create(
                model=self.model_name,
                input=prompt,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "clarification_needed": {"type": "boolean"},
                            "clarification_question": {
                                "type": ["string", "null"]
                            },
                            "sql": {"type": ["string", "null"]},
                            "explanation": {"type": ["string", "null"]},
                        },
                        "required": [
                            "clarification_needed",
                            "clarification_question",
                            "sql",
                            "explanation",
                        ],
                        "additionalProperties": False,
                    },
                },
                store=False,
            )
            raw = getattr(response, "output_text", "") or ""
        except Exception as exc:  # noqa: BLE001
            return GenerationResult(
                clarification_needed=False,
                clarification_question=None,
                sql=None,
                explanation=None,
                raw=None,
                error=self._gemini_error_message(exc),
                provider="gemini",
                model=self.model_name,
            )
        return self._parse_response(raw, question, provider="gemini")

    def _gemini_error_message(self, exc: Exception) -> str:
        code = getattr(exc, "code", None)
        status = str(getattr(exc, "status", "")).upper()
        error_type = type(exc).__name__.lower()

        if code == 404 or status == "NOT_FOUND" or error_type == "notfound":
            return (
                f"Gemini model '{self.model_name}' was not found or is no longer "
                "available to this API key. Set GEMINI_MODEL to a model currently "
                "available through the Gemini Interactions API "
                f"(for example, '{DEFAULT_GEMINI_MODEL}')."
            )
        if code in (401, 403) or status in ("UNAUTHENTICATED", "PERMISSION_DENIED"):
            return (
                "Gemini API rejected the credentials or project permissions. "
                "Check GEMINI_API_KEY and Gemini API access in Google AI Studio."
            )
        if code == 429 or status in ("RESOURCE_EXHAUSTED", "TOO_MANY_REQUESTS"):
            return (
                f"Gemini quota or rate limit is exhausted for model "
                f"'{self.model_name}'. Wait for the quota to reset or review "
                "the Google AI Studio project's plan, billing, and model-specific "
                "rate limits. This request was not automatically retried."
            )
        if code == 400 or status == "INVALID_ARGUMENT":
            return (
                "Gemini rejected the request configuration. Check that GEMINI_MODEL "
                "supports the Interactions API and structured JSON output."
            )
        if isinstance(code, int) and code >= 500 or status in (
            "INTERNAL",
            "UNAVAILABLE",
            "DEADLINE_EXCEEDED",
        ):
            return "Gemini is temporarily unavailable. Please retry shortly."

        return (
            f"Gemini request failed ({type(exc).__name__}) for model "
            f"'{self.model_name}'. Check the model setting and Gemini API status."
        )

    def _generate_openrouter(
        self, prompt: str, question: str
    ) -> GenerationResult:
        assert self._client is not None
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.openrouter_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": "You are an expert MySQL data analyst."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        }
        try:
            resp = self._client.post(url, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            raw = data["choices"][0]["message"]["content"] or ""
        except Exception as exc:  # noqa: BLE001
            return GenerationResult(
                clarification_needed=False,
                clarification_question=None,
                sql=None,
                explanation=None,
                raw=None,
                error=f"OpenRouter request failed: {type(exc).__name__}",
                provider="openrouter",
                model=self.model_name,
            )
        return self._parse_response(raw, question, provider="openrouter")

    def _generate_ollama(
        self, prompt: str, question: str
    ) -> GenerationResult:
        assert self._client is not None
        url = f"{self.ollama_host.rstrip('/')}/api/generate"
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1},
        }
        try:
            resp = self._client.post(url, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            raw = data.get("response", "") or ""
        except Exception as exc:  # noqa: BLE001
            return GenerationResult(
                clarification_needed=False,
                clarification_question=None,
                sql=None,
                explanation=None,
                raw=None,
                error=f"Ollama request failed: {type(exc).__name__} "
                f"(is Ollama running at {self.ollama_host}?)",
                provider="ollama",
                model=self.model_name,
            )
        return self._parse_response(raw, question, provider="ollama")

    def _generate_openai_compatible(
        self, prompt: str, question: str
    ) -> GenerationResult:
        """Generate via an OpenAI-compatible API (NVIDIA Nemotron, OpenRouter, Together, Groq, etc.)."""
        assert self._client is not None
        key = self.openai_api_key or self.api_key
        url = self.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": "You are an expert MySQL data analyst."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        }
        try:
            resp = self._client.post(url, headers=headers, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            raw = data["choices"][0]["message"]["content"] or ""
        except Exception as exc:  # noqa: BLE001
            return GenerationResult(
                clarification_needed=False,
                clarification_question=None,
                sql=None,
                explanation=None,
                raw=None,
                error=f"OpenAI-compatible request failed: {type(exc).__name__}",
                provider="openai",
                model=self.model_name,
            )
        return self._parse_response(raw, question, provider="openai")

    # ------------------------------------------------------------------ #
    # Prompt building / response parsing
    # ------------------------------------------------------------------ #
    def _build_prompt(self, question: str, schema: dict) -> str:
        schema_text = self._format_schema(schema)
        return f"""You are an expert MySQL data analyst. Convert the user's natural-language
question into a single read-only MySQL SELECT query.

DATABASE SCHEMA (only these tables may be referenced):
{schema_text}

TABLE RELATIONSHIPS (foreign keys):
- orders.customer_id -> customers.customer_id
- order_items.order_id -> orders.order_id
- order_items.product_id -> products.product_id
- products.category_id -> categories.category_id
- payments.order_id -> orders.order_id

SQL GENERATION RULES:
- Return exactly ONE SELECT statement. No INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE.
- No multiple statements. No SELECT INTO or file operations (OUTFILE/DUMPFILE/LOAD_FILE).
- No stored-procedure calls (CALL). No MySQL system schemas (mysql.*, information_schema.*).
- Use explicit column names, never SELECT *.
- Only reference these tables: customers, products, categories, orders, order_items, payments.
- Define sales value as order_items.quantity * products.price.
- Define paid revenue as payments.amount where payments.status = 'completed'.
- Define refunds as payments.amount where payments.status = 'refunded'.
- Do NOT treat order totals and collected payment revenue as identical.
- Add a sensible LIMIT to bound results (maximum 500 rows).

CLARIFICATION POLICY:
- If the question is genuinely ambiguous (for example "best customers" without saying
  whether best means highest spending, most orders, etc.; or "revenue" without specifying
  sales value vs completed payments), set clarification_needed to true and provide a
  specific clarification_question. Set sql to null.
- If the intent is clear, clarification_needed is false and provide the SQL.

Respond with a JSON object containing exactly these keys:
- clarification_needed (boolean)
- clarification_question (string or null)
- sql (string or null)
- explanation (brief plain-English description of the intended query)

User question: {question}"""

    @staticmethod
    def _format_schema(schema: dict) -> str:
        if not schema:
            return "(schema unavailable)"
        lines = []
        for table, info in schema.items():
            columns = ", ".join(
                c["name"] for c in info.get("columns", [])
            )
            pks = ", ".join(info.get("primary_keys", []))
            fks = "; ".join(
                f"{', '.join(fk.get('columns', []))} -> {fk.get('referred_table')}"
                f"({', '.join(fk.get('referred_columns', []))})"
                for fk in info.get("foreign_keys", [])
            )
            lines.append(
                f"- {table}: columns=[{columns}] | PK=[{pks}] | FKs=[{fks}]"
            )
        return "\n".join(lines)

    @staticmethod
    def _parse_response(
        raw: str, question: str, provider: str = "unknown"
    ) -> GenerationResult:
        text = raw.strip()
        # Strip markdown fences if present.
        if text.startswith("```"):
            parts = text.split("```", 2)
            text = parts[1] if len(parts) > 1 else ""
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return GenerationResult(
                clarification_needed=False,
                clarification_question=None,
                sql=None,
                explanation=(
                    "The model returned a non-JSON response. No SQL was generated."
                ),
                raw=raw,
                error="Model response was not valid JSON.",
                provider=provider,
            )

        return GenerationResult(
            clarification_needed=bool(data.get("clarification_needed", False)),
            clarification_question=data.get("clarification_question"),
            sql=data.get("sql"),
            explanation=data.get("explanation"),
            raw=raw,
            provider=provider,
        )


def get_ai_engine() -> AIEngine:
    """Factory returning a configured AIEngine instance."""
    return AIEngine()
