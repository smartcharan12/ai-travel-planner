"""StructuredLLM: parsing, validation, bounded retry, timeouts and error mapping."""

from __future__ import annotations

import asyncio
import json

import pytest
from langchain_core.exceptions import (
    ModelAuthenticationError,
    ModelNotFoundError,
    ModelRateLimitError,
    ModelTimeoutError,
)
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.core.exceptions import (
    ConfigurationError,
    LLMAuthError,
    LLMError,
    LLMOutputError,
    LLMTimeoutError,
    RateLimitError,
)
from app.llm.client import StructuredLLM, parse_json_reply
from app.llm.factory import create_structured_llm
from app.schemas import ResearchExtraction
from tests.fakes import ScriptedChatModel, SlowChatModel, goa_extraction_json

VALID = json.dumps(goa_extraction_json())


def _llm(model, retries=1, timeout=5.0) -> StructuredLLM:
    return StructuredLLM(
        model,
        model_name="test-model",
        timeout_seconds=timeout,
        output_retries=retries,
        native_json_schema=False,
    )


def _generate(llm):
    return asyncio.run(llm.generate([HumanMessage("extract")], ResearchExtraction))


def test_valid_json_is_parsed_into_schema_and_usage_recorded():
    model = ScriptedChatModel(
        script=[VALID], usage={"input_tokens": 1200, "output_tokens": 300, "total_tokens": 1500}
    )
    result = _generate(_llm(model))
    assert isinstance(result.value, ResearchExtraction)
    assert result.value.attractions[0].name == "Baga Beach"
    assert (result.usage.calls, result.usage.input_tokens, result.usage.output_tokens) == (1, 1200, 300)


def test_tokens_unknown_when_provider_does_not_report_them():
    result = _generate(_llm(ScriptedChatModel(script=[VALID])))
    assert result.usage.input_tokens is None  # unknown, not zero


def test_markdown_code_fences_are_tolerated():
    assert parse_json_reply(f"```json\n{VALID}\n```", ResearchExtraction).hotels


def test_malformed_json_is_retried_with_feedback_then_succeeds():
    model = ScriptedChatModel(script=["Sure! Here is the JSON: {oops", VALID])
    result = _generate(_llm(model, retries=1))
    assert result.usage.calls == 2
    feedback = model.received[1][-1].text
    assert "not valid JSON" in feedback and "ONLY one JSON object" in feedback


def test_schema_violation_feedback_names_the_field():
    bad = goa_extraction_json()
    bad["attractions"][0]["opening_hours"] = "9-5"  # invented field -> extra="forbid"
    model = ScriptedChatModel(script=[json.dumps(bad), VALID])
    _generate(_llm(model, retries=1))
    assert "attractions.0.opening_hours" in model.received[1][-1].text


def test_gives_up_after_bounded_retries():
    model = ScriptedChatModel(script=["not json", "still not json", VALID])
    with pytest.raises(LLMOutputError) as info:
        _generate(_llm(model, retries=1))
    assert info.value.details == {"reason": "invalid_json", "attempts": 2}
    assert len(model.script) == 1  # third reply never requested


def test_wrong_types_raise_schema_validation_reason():
    model = ScriptedChatModel(script=['{"attractions": "not a list"}'])
    with pytest.raises(LLMOutputError) as info:
        _generate(_llm(model, retries=0))
    assert info.value.details["reason"] == "schema_validation"


@pytest.mark.parametrize(
    "provider_exc,expected",
    [
        (ModelRateLimitError("429 quota"), RateLimitError),
        (ModelAuthenticationError("API key not valid"), LLMAuthError),
        (ModelTimeoutError("deadline"), LLMTimeoutError),
        (ModelNotFoundError("no such model"), ConfigurationError),
        (RuntimeError("socket closed; key=AIzaSECRET"), LLMError),
    ],
)
def test_provider_errors_become_domain_errors_without_leaking(provider_exc, expected):
    with pytest.raises(expected) as info:
        _generate(_llm(ScriptedChatModel(script=[provider_exc])))
    assert "AIzaSECRET" not in info.value.public_message and "AIzaSECRET" not in str(info.value.details)


def test_hard_timeout_even_if_provider_hangs():
    with pytest.raises(LLMTimeoutError):
        _generate(_llm(SlowChatModel(delay_seconds=5), timeout=0.05))


def test_factory_builds_gemini_without_network_and_masks_key(make_settings):
    llm = create_structured_llm(
        make_settings(llm_api_key="AIza-test-key", tavily_api_key="t"), temperature=0.0
    )
    assert isinstance(llm._model, ChatGoogleGenerativeAI)
    assert llm.model_name == "gemini-2.5-flash" and llm._model.temperature == 0.0
    assert "AIza-test-key" not in repr(llm._model)
    assert llm.is_demo is False


def test_gemini_request_carries_json_mode_and_schema(make_settings):
    llm = create_structured_llm(make_settings(llm_api_key="k", tavily_api_key="t"), temperature=0.0)
    request = llm._model._prepare_request(
        [HumanMessage("hi")],
        response_mime_type="application/json",
        response_json_schema=ResearchExtraction.model_json_schema(),
    )
    assert request["config"].response_mime_type == "application/json"
    assert request["config"].response_json_schema["title"] == "ResearchExtraction"


def test_factory_refuses_missing_gemini_key(make_settings):
    with pytest.raises(ConfigurationError) as info:
        create_structured_llm(make_settings(tavily_api_key="t"), temperature=0.0)
    assert info.value.details == {"missing": ["GEMINI_API_KEY"]}


def test_gemini_api_key_env_var_is_read(monkeypatch, make_settings):
    monkeypatch.setenv("GEMINI_API_KEY", "from-env")
    assert make_settings().llm_api_key.get_secret_value() == "from-env"
