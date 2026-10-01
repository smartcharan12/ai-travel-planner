"""Build the configured chat model. The only file that imports a provider SDK.

Changing LLM vendor later means adding a branch here (e.g. ChatAnthropic,
ChatOpenAI); prompts, parsing, grounding and the workflow stay unchanged,
because they only see LangChain's common ``BaseChatModel`` interface.
"""

from __future__ import annotations

from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import Settings
from app.core.exceptions import ConfigurationError
from app.llm.client import StructuredLLM
from app.llm.demo_model import DemoChatModel


def create_structured_llm(settings: Settings, *, temperature: float) -> StructuredLLM:
    if settings.llm_provider == "fake":
        return StructuredLLM(
            DemoChatModel(),
            model_name="demo-model",
            timeout_seconds=settings.llm_timeout_seconds,
            output_retries=settings.llm_output_retries,
            native_json_schema=False,
            is_demo=True,
        )
    if settings.llm_provider == "gemini":
        if settings.llm_api_key is None:
            raise ConfigurationError(details={"missing": ["GEMINI_API_KEY"]})
        chat_model = ChatGoogleGenerativeAI(
            model=settings.llm_model,
            google_api_key=settings.llm_api_key,  # SecretStr: stays masked in reprs/logs
            temperature=temperature,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,  # SDK retries transient network/5xx errors
        )
        return StructuredLLM(
            chat_model,
            model_name=settings.llm_model,
            # Slightly above the SDK timeout so the SDK's own timeout normally fires first.
            timeout_seconds=settings.llm_timeout_seconds * (settings.llm_max_retries + 1) + 5,
            output_retries=settings.llm_output_retries,
            native_json_schema=True,
            input_cost_per_million_usd=settings.llm_input_cost_per_million_usd,
            output_cost_per_million_usd=settings.llm_output_cost_per_million_usd,
        )
    raise ConfigurationError(details={"unknown_llm_provider": settings.llm_provider})
