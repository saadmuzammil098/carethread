"""Config-shape tests only, no live provider calls (see task-2/README.md's
'why these tests don't hit a real LLM' for why CI can't and shouldn't)."""

from src.llm_gateway import MODEL_GROUP, build_router


def test_router_has_all_three_providers():
    router = build_router()
    model_names = {m["model_name"] for m in router.get_model_list()}
    assert model_names == {
        MODEL_GROUP,
        "carethread-narrative-groq",
        "carethread-narrative-gemini",
    }


def test_primary_model_group_is_ollama():
    router = build_router()
    primary = next(
        m for m in router.get_model_list() if m["model_name"] == MODEL_GROUP
    )
    assert primary["litellm_params"]["model"].startswith("ollama/")


def test_fallback_chain_is_groq_then_gemini():
    router = build_router()
    assert router.fallbacks == [
        {MODEL_GROUP: ["carethread-narrative-groq", "carethread-narrative-gemini"]}
    ]
