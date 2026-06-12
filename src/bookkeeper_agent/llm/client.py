from __future__ import annotations

from typing import Protocol, runtime_checkable

from bookkeeper_agent.llm.types import (
    BillExtraction,
    CategorizationContext,
    CategorySuggestion,
    EmailContext,
)


@runtime_checkable
class LlmClient(Protocol):
    """The two model operations the bills pipeline needs. Real impl:
    AnthropicLlmClient. Fake: FakeLlmClient."""

    def classify_and_extract(self, ctx: EmailContext) -> BillExtraction: ...

    def categorize(self, ctx: CategorizationContext) -> CategorySuggestion: ...


class FakeLlmClient:
    """In-memory LlmClient for pipeline tests. Returns the configured result
    and records the contexts it was called with."""

    def __init__(
        self,
        extraction: BillExtraction | None = None,
        suggestion: CategorySuggestion | None = None,
    ) -> None:
        self._extraction = extraction
        self._suggestion = suggestion
        self.classify_calls: list[EmailContext] = []
        self.categorize_calls: list[CategorizationContext] = []

    def set_extraction(self, extraction: BillExtraction) -> None:
        self._extraction = extraction

    def set_suggestion(self, suggestion: CategorySuggestion) -> None:
        self._suggestion = suggestion

    def classify_and_extract(self, ctx: EmailContext) -> BillExtraction:
        self.classify_calls.append(ctx)
        if self._extraction is None:
            raise AssertionError("FakeLlmClient.classify_and_extract: no extraction configured")
        return self._extraction

    def categorize(self, ctx: CategorizationContext) -> CategorySuggestion:
        self.categorize_calls.append(ctx)
        if self._suggestion is None:
            raise AssertionError("FakeLlmClient.categorize: no suggestion configured")
        return self._suggestion
