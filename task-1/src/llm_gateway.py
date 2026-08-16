"""LiteLLM Router gateway: one call surface, three backing providers.

Primary is local Ollama (no per-token cost, no network dependency for
the common case), falling back to Groq then Gemini if Ollama is
unreachable or errors. This is what "Done when: killing the primary LLM
provider fails over with no visible outage" is actually about, the
Router, not any one provider, is what CareThread's narrative feature
depends on.

Deliberately narrow: this gateway backs exactly one thing today,
`narrative.py`'s flag-rephrasing call (see that module for why an LLM
touches CareThread at all, given Task 1's flagger is fully rule-based).
CareThread Task 3's full agent will likely need a broader model_list
(tool-calling-capable models, per the roadmap's Hugging Face section),
that's this module's problem to grow into then, not now.
"""
from __future__ import annotations

import os

from litellm import Router

MODEL_GROUP = "carethread-narrative"
_GROQ_MODEL_GROUP = "carethread-narrative-groq"
_GEMINI_MODEL_GROUP = "carethread-narrative-gemini"

# Ollama's local server, no API key needed. Model chosen for the same
# reason TutorLoop's agent tasks pick Llama/Qwen Instruct, see the
# roadmap's Hugging Face section, decent instruction-following in a
# size that runs on a laptop.
_OLLAMA_MODEL = os.environ.get("CARETHREAD_OLLAMA_MODEL", "ollama/qwen2.5:7b")
_OLLAMA_API_BASE = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434")

# Groq and Gemini both need their real API key env vars
# (GROQ_API_KEY, GEMINI_API_KEY) to actually work; litellm reads those
# directly, nothing CareThread-specific to configure here. A missing
# key surfaces as this provider failing at call time, which is exactly
# the case the Router's fallback chain exists to route around.
_GROQ_MODEL = os.environ.get("CARETHREAD_GROQ_MODEL", "groq/llama-3.3-70b-versatile")
_GEMINI_MODEL = os.environ.get("CARETHREAD_GEMINI_MODEL", "gemini/gemini-flash-latest")


def build_router() -> Router:
    return Router(
        model_list=[
            {
                "model_name": MODEL_GROUP,
                "litellm_params": {
                    "model": _OLLAMA_MODEL,
                    "api_base": _OLLAMA_API_BASE,
                },
            },
            {
                "model_name": _GROQ_MODEL_GROUP,
                "litellm_params": {"model": _GROQ_MODEL},
            },
            {
                "model_name": _GEMINI_MODEL_GROUP,
                "litellm_params": {"model": _GEMINI_MODEL},
            },
        ],
        fallbacks=[{MODEL_GROUP: [_GROQ_MODEL_GROUP, _GEMINI_MODEL_GROUP]}],
        # One retry per provider before falling through, not the
        # default 2-3: a hung local Ollama should hand off to Groq
        # quickly, not stall the request retrying the same dead
        # provider.
        num_retries=0,
        timeout=15,
    )


# Module-level singleton: a Router holds provider client state (Ollama's
# base URL, retry counters) that's cheap to build once and reuse across
# requests, same reasoning as every other module-level client in this
# roadmap (e.g. RxGround's Chroma client).
router = build_router()
