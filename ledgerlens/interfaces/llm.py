"""LLM client seam — generator behind a provider-neutral interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ledgerlens.config import Settings, get_settings


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class LLMResponse:
    text: str
    usage: LLMUsage | None
    model: str


class LLMClient(ABC):
    @abstractmethod
    def generate(
        self,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
    ) -> LLMResponse: ...


_ABSTAIN_TEXT = (
    "I don't have sufficient retrieved evidence to answer that question confidently. "
    "Please try rephrasing or narrowing the scope."
)


class FakeLLM(LLMClient):
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def generate(
        self,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
    ) -> LLMResponse:
        del system, messages, max_tokens  # unused in fake backend
        return LLMResponse(
            text=_ABSTAIN_TEXT,
            usage=LLMUsage(input_tokens=0, output_tokens=0),
            model=self._settings.llm_model,
        )


class LiteLLMClient(LLMClient):
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def generate(
        self,
        system: str,
        messages: list[dict[str, str]],
        max_tokens: int | None = None,
    ) -> LLMResponse:
        import litellm  # noqa: PLC0415 — lazy import per seam pattern

        cap = max_tokens if max_tokens is not None else self._settings.max_output_tokens
        payload = [{"role": "system", "content": system}, *messages]
        response = litellm.completion(
            model=self._settings.llm_model,
            messages=payload,
            max_tokens=cap,
            api_key=self._settings.anthropic_api_key,
        )
        choice = response.choices[0]
        usage = response.usage
        return LLMResponse(
            text=choice.message.content or "",
            usage=LLMUsage(
                input_tokens=int(usage.prompt_tokens),
                output_tokens=int(usage.completion_tokens),
            )
            if usage
            else None,
            model=str(response.model or self._settings.llm_model),
        )
