"""
Provider-agnostic LLM client.

Supports three providers via two SDKs:
  - claude  → anthropic SDK  → Anthropic API
  - ollama  → openai SDK     → http://localhost:11434/v1  (local, free)
  - openai  → openai SDK     → https://api.openai.com/v1

Usage:
    client = LLMClient.from_env()
    response = client.create(messages, tools, system)

    if response.stop_reason == "tool_use":
        for call in response.tool_calls:
            result = run_tool(call["name"], call["input"])
        messages += client.build_tool_result_messages(response.tool_calls, results)
    else:
        print(response.text)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from src.egress import ensure_allowed_url
from src.env_loader import load_env
load_env()


# ---------------------------------------------------------------------------
# Normalised response — same shape regardless of provider
# ---------------------------------------------------------------------------

@dataclass
class NormalizedResponse:
    stop_reason: str                    # "end_turn" | "tool_use"
    text: str                           # final assistant text (empty during tool_use)
    tool_calls: list[dict]              # [{"id": str, "name": str, "input": dict}]
    provider: str = ""                  # "claude" | "groq" | "openai" | "ollama" | ...
    model: str = ""                     # model name used for this call
    usage: dict = field(default_factory=dict)  # normalized usage tokens/cost-like fields (best-effort)
    raw: Any = field(default=None, repr=False)  # original SDK object (for serialisation)


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class LLMClient:
    supports_vision: bool = False

    def create(self, messages: list, tools: list, system: str) -> NormalizedResponse:
        raise NotImplementedError

    def convert_tools(self, anthropic_tools: list) -> list:
        """Convert tool definitions from Anthropic format to this provider's format."""
        raise NotImplementedError

    def build_tool_result_messages(self, tool_calls: list[dict], results: list[str]) -> list[dict]:
        """Build the provider-specific message(s) that feed tool results back."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @staticmethod
    def from_env(provider: str = None, model: str = None) -> "LLMClient":
        provider = (provider or os.getenv("MODEL_PROVIDER", "claude")).lower()
        model    = model or os.getenv("MODEL_NAME", "claude-sonnet-4-6")

        if provider == "claude":
            return ClaudeClient(model=model)
        elif provider == "groq":
            return OpenAICompatClient(
                model=model,
                base_url="https://api.groq.com/openai/v1",
                api_key=os.getenv("GROQ_API_KEY", ""),
                provider="groq",
            )
        elif provider in ("ollama", "openai"):
            base_url = (
                os.getenv("OLLAMA_URL", "http://localhost:11434/v1")
                if provider == "ollama"
                else "https://api.openai.com/v1"
            )
            api_key = (
                os.getenv("OPENAI_API_KEY", "ollama")   # Ollama ignores the key
                if provider == "openai"
                else os.getenv("OPENAI_API_KEY", "ollama")
            )
            return OpenAICompatClient(model=model, base_url=base_url, api_key=api_key,
                                      provider=provider)
        else:
            raise ValueError(f"Unknown MODEL_PROVIDER: {provider!r}. Use claude, groq, ollama, or openai.")


# ---------------------------------------------------------------------------
# Claude (Anthropic SDK)
# ---------------------------------------------------------------------------

class ClaudeClient(LLMClient):
    supports_vision = True

    def __init__(self, model: str):
        import anthropic
        self.model  = model
        self._client = anthropic.Anthropic()

    def convert_tools(self, anthropic_tools: list) -> list:
        return anthropic_tools  # already in the right format

    def create(self, messages: list, tools: list, system: str) -> NormalizedResponse:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system,
            tools=self.convert_tools(tools),
            messages=messages,
        )

        usage = {}
        try:
            # Anthropic usage fields vary by SDK/version; normalize best-effort.
            u = getattr(response, "usage", None)
            if u is not None:
                usage = {
                    "input": getattr(u, "input_tokens", 0) or 0,
                    "output": getattr(u, "output_tokens", 0) or 0,
                    "cacheRead": getattr(u, "cache_read_input_tokens", 0) or 0,
                    "cacheWrite": getattr(u, "cache_creation_input_tokens", 0) or 0,
                }
                usage["totalTokens"] = usage["input"] + usage["output"] + usage["cacheRead"] + usage["cacheWrite"]
        except Exception:
            usage = {}

        if response.stop_reason == "tool_use":
            calls = [
                {"id": b.id, "name": b.name, "input": b.input}
                for b in response.content
                if b.type == "tool_use"
            ]
            return NormalizedResponse(
                stop_reason="tool_use",
                text="",
                tool_calls=calls,
                provider="claude",
                model=self.model,
                usage=usage,
                raw=response,
            )

        text = next((b.text for b in response.content if hasattr(b, "text")), "")
        return NormalizedResponse(
            stop_reason="end_turn",
            text=text,
            tool_calls=[],
            provider="claude",
            model=self.model,
            usage=usage,
            raw=response,
        )

    def build_tool_result_messages(self, tool_calls: list[dict],
                                   results: list[str]) -> list[dict]:
        """Anthropic expects a single user message containing tool_result blocks."""
        return [{
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "content": result,
                }
                for call, result in zip(tool_calls, results)
            ]
        }]

    def assistant_message_from_raw(self, raw) -> dict:
        """Serialise the raw Anthropic response into a messages-list entry."""
        return {"role": "assistant", "content": raw.content}


# ---------------------------------------------------------------------------
# OpenAI-compatible (Ollama + OpenAI)
# ---------------------------------------------------------------------------

class OpenAICompatClient(LLMClient):
    # Vision depends on the model; default conservative False.
    # Users can set MODEL_SUPPORTS_VISION=true in .env to enable.
    @property
    def supports_vision(self) -> bool:  # type: ignore[override]
        return os.getenv("MODEL_SUPPORTS_VISION", "false").lower() == "true"

    def __init__(self, model: str, base_url: str, api_key: str, provider: str):
        from openai import OpenAI
        ensure_allowed_url(base_url)
        self.model    = model
        self.provider = provider
        self._client  = OpenAI(base_url=base_url, api_key=api_key)

    def convert_tools(self, anthropic_tools: list) -> list:
        """Convert Anthropic tool format → OpenAI function-calling format."""
        converted = []
        for t in anthropic_tools:
            converted.append({
                "type": "function",
                "function": {
                    "name":        t["name"],
                    "description": t.get("description", ""),
                    "parameters":  t.get("input_schema", {"type": "object", "properties": {}}),
                }
            })
        return converted

    def create(self, messages: list, tools: list, system: str) -> NormalizedResponse:
        # Build message list with system prefix
        oai_messages = [{"role": "system", "content": system}] + messages

        response = self._client.chat.completions.create(
            model=self.model,
            tools=self.convert_tools(tools),
            messages=oai_messages,
        )

        choice  = response.choices[0]
        message = choice.message

        usage = {}
        try:
            u = getattr(response, "usage", None)
            if u is not None:
                prompt = getattr(u, "prompt_tokens", 0) or 0
                completion = getattr(u, "completion_tokens", 0) or 0
                total = getattr(u, "total_tokens", prompt + completion) or (prompt + completion)
                usage = {"input": prompt, "output": completion, "totalTokens": total}
        except Exception:
            usage = {}

        if choice.finish_reason == "tool_calls" and message.tool_calls:
            def _parse_input(tc):
                try:
                    return json.loads(tc.function.arguments) if tc.function.arguments else {}
                except (json.JSONDecodeError, TypeError):
                    return {}
            calls = [
                {
                    "id":    tc.id,
                    "name":  tc.function.name,
                    "input": _parse_input(tc),
                }
                for tc in message.tool_calls
            ]
            return NormalizedResponse(
                stop_reason="tool_use",
                text="",
                tool_calls=calls,
                provider=self.provider,
                model=self.model,
                usage=usage,
                raw=response,
            )

        text = message.content or ""
        return NormalizedResponse(
            stop_reason="end_turn",
            text=text,
            tool_calls=[],
            provider=self.provider,
            model=self.model,
            usage=usage,
            raw=response,
        )

    def build_tool_result_messages(self, tool_calls: list[dict],
                                   results: list[str]) -> list[dict]:
        """OpenAI expects one message per tool result, each with role='tool'."""
        return [
            {
                "role":         "tool",
                "tool_call_id": call["id"],
                "content":      result,
            }
            for call, result in zip(tool_calls, results)
        ]

    def assistant_message_from_raw(self, raw) -> dict:
        """Serialise OpenAI response into a messages-list entry."""
        msg = raw.choices[0].message
        content = []
        if msg.content:
            content.append({"type": "text", "text": msg.content})
        if msg.tool_calls:
            for tc in msg.tool_calls:
                content.append({
                    "type":     "tool_use",
                    "id":       tc.id,
                    "name":     tc.function.name,
                    "input":    json.loads(tc.function.arguments),
                })
        return {"role": "assistant", "content": content}
