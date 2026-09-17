# src/helper.py
"""
LLM factory with provider abstraction.

Switch providers via LLM_PROVIDER env var:
  groq    → Groq (default, quota-limited free tier)
  gemini  → Google Gemini (generous free tier: 1M tokens/day)
  fake    → Deterministic FakeLLM (for tests, zero API calls)
"""
import os
import json
from langchain.prompts import PromptTemplate
from langchain.output_parsers import PydanticOutputParser
from typing import Dict

from src.config import (
    LLM_PROVIDER,
    GROQ_API_KEY, GROQ_MODEL_NAME, GROQ_MAX_RETRIES, GROQ_TIMEOUT,
    GEMINI_API_KEY, GEMINI_MODEL_NAME,
    MSG_JSON_FILE, logger,
)
from src.booking_agent.schemas import BookingRequest
from src.booking_agent.prompt_config import REQUEST_TEMPLATE, SUCCESS_EXAMPLE, MISSING_EXAMPLE

REQUIRED_FIELDS = [
    "start_date", "start_time", "duration_hours",
    "equipments", "user_name", "capacity"
]


# ── Provider builders ──────────────────────────────────────────────────────

def _build_groq(with_tools: bool = False, temp: float = 0.0):
    from langchain_groq import ChatGroq
    llm = ChatGroq(
        model_name=GROQ_MODEL_NAME,
        groq_api_key=GROQ_API_KEY,
        temperature=temp,
        max_retries=GROQ_MAX_RETRIES,
        timeout=GROQ_TIMEOUT,
    )
    logger.info(">>>> Load Groq: %s (with_tools=%s)", GROQ_MODEL_NAME, with_tools)
    if with_tools:
        from src.booking_agent.tools import ALL_TOOLS
        return llm.bind_tools(ALL_TOOLS)
    return llm


def _build_gemini(with_tools: bool = False, temp: float = 0.0):
    from langchain_google_genai import ChatGoogleGenerativeAI
    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL_NAME,
        google_api_key=GEMINI_API_KEY,
        temperature=temp,
        max_retries=3,
        timeout=60,
    )
    logger.info(">>>> Load Gemini: %s (with_tools=%s)", GEMINI_MODEL_NAME, with_tools)
    if with_tools:
        from src.booking_agent.tools import ALL_TOOLS
        return llm.bind_tools(ALL_TOOLS)
    return llm


def _build_fake(with_tools: bool = False, temp: float = 0.0):
    """Load FakeLLM — zero API calls, deterministic. Only for tests."""
    from tests.fake_llm import FakeLLM
    llm = FakeLLM(with_tools=with_tools)
    logger.info(">>>> Load FakeLLM (with_tools=%s)", with_tools)
    return llm


_PROVIDERS = {
    "groq": _build_groq,
    "gemini": _build_gemini,
    "fake": _build_fake,
}


def initialize_llm(
    name: str = None,       # legacy arg — ignored if LLM_PROVIDER is set
    temp: float = 0.0,
    with_tools: bool = False,
):
    """
    Return an LLM instance based on LLM_PROVIDER env var.
    Supports a legacy `name` kwarg for backwards compatibility
    (nodes.py calls initialize_llm(name="groq") in parse_request).
    """
    # Determine effective provider
    # If caller explicitly passes name="groq" and provider is "fake", honour "fake"
    # (test override wins over node hardcode)
    provider = os.getenv("LLM_PROVIDER", LLM_PROVIDER).lower()
    if provider not in _PROVIDERS:
        raise ValueError(
            f"Unknown LLM_PROVIDER: {provider!r}. "
            f"Valid options: {list(_PROVIDERS)}"
        )
    return _PROVIDERS[provider](with_tools=with_tools, temp=temp)


# ── Prompt helpers (unchanged) ─────────────────────────────────────────────

def apply_request_prompt(parsing_schema: PydanticOutputParser) -> PromptTemplate:
    """Apply the prompt template to the LLM."""
    prompt_template = PromptTemplate(
        input_variables=["user_request", "current_date", "current_time"],
        template=REQUEST_TEMPLATE,
        partial_variables={
            "parsing_schema": parsing_schema.get_format_instructions(),
            "successful_example": json.dumps(SUCCESS_EXAMPLE, indent=2),
            "missing_example": json.dumps(MISSING_EXAMPLE, indent=2),
        })
    return prompt_template


def get_missing_fields(parsed_request: dict) -> list:
    """Get a list of missing fields from the parsed request."""
    return [
        field for field in REQUIRED_FIELDS
        if not parsed_request.get(field)
        or (field == "duration_hours" and parsed_request[field] <= 0)
    ]


def load_clarification_msgs(filepath: str = MSG_JSON_FILE) -> Dict:
    """Load clarification messages from a JSON file."""
    with open(filepath, "r") as file:
        return json.load(file)
