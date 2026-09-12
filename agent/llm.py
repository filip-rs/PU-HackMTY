"""OpenAI-compatible LLM client for the investigation loop (#22).

The single place that talks to the model. It :

- talks only to the endpoint configured in ``.env`` (AGENTS.md rule 8) and never
  logs or prints the API key;
- caches responses on disk so a demo re-run costs zero network;
- retries connection errors / timeouts / HTTP 5xx / 429 with 1-2-4s backoff;
- never raises on a malformed tool call (``args={}`` and ``parse_error`` set);
- exposes :class:`FakeLLM`, a scripted stand-in with the same ``.chat`` signature,
  so #13 can be built and tested without the cluster.

This module never opens a dataset or anything under ``hidden/``.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Settings

ROOT = Path(__file__).resolve().parents[1]

# Connection errors (APITimeoutError is a subclass of APIConnectionError), 429
# (RateLimitError) and 5xx (InternalServerError) are retryable; every other 4xx
# is a caller bug and must not be retried.
_RETRYABLE = ("APIConnectionError", "RateLimitError", "InternalServerError")


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict  # parsed JSON arguments; {} when parsing failed
    parse_error: str = ""  # set when `arguments` was not valid JSON


@dataclass
class Reply:
    text: str  # assistant content; "" when the model only called tools
    tool_calls: list[ToolCall]
    cached: bool
    usage: dict  # {"prompt_tokens","completion_tokens"} when reported, else {}
    raw: dict  # the whole response as a plain dict (goes into the step log)


def assistant_message(reply: Reply) -> dict:
    """The dict to append to ``messages`` after a call, in OpenAI shape."""
    msg: dict = {"role": "assistant", "content": reply.text}
    if reply.tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.args, ensure_ascii=False)},
            }
            for tc in reply.tool_calls
        ]
    return msg


def tool_message(call: ToolCall, result) -> dict:
    """The dict to append to ``messages`` after a tool ran."""
    return {
        "role": "tool",
        "tool_call_id": call.id,
        "name": call.name,
        "content": json.dumps(result, ensure_ascii=False, default=str),
    }


class LLM:
    """Thin wrapper over ``openai.OpenAI`` with caching and retries."""

    def __init__(
        self,
        settings: Settings,
        *,
        client=None,
        cache_dir: Path | None = ROOT / ".cache" / "llm",
        temperature: float = 0.0,
        timeout: float = 120.0,
        max_retries: int = 3,
    ) -> None:
        import openai

        self._openai = openai
        self.settings = settings
        self.client = client if client is not None else openai.OpenAI(
            base_url=settings.base_url, api_key=settings.api_key, timeout=timeout
        )
        self.cache_dir = cache_dir
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries

    # -- cache -------------------------------------------------------------
    def _cache_enabled(self) -> bool:
        return self.cache_dir is not None and os.environ.get("LLM_CACHE", "1") != "0"

    def _cache_key(self, messages, tools, tool_choice, max_tokens) -> str:
        data = {
            "model": self.settings.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        s = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(s.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalise(resp) -> dict:
        """Return the response as a plain dict (model_dump when it is an object)."""
        if hasattr(resp, "model_dump"):
            return resp.model_dump()
        return dict(resp)

    @staticmethod
    def _build_reply(raw: dict, *, cached: bool) -> Reply:
        choice = raw.get("choices") or [{}]
        msg = choice[0].get("message", {}) if isinstance(choice[0], dict) else {}
        text = msg.get("content") or ""
        tool_calls: list[ToolCall] = []
        for tc in msg.get("tool_calls") or []:
            func = tc.get("function", {}) if isinstance(tc, dict) else {}
            args_str = func.get("arguments") if isinstance(func, dict) else ""
            args_str = args_str or ""
            try:
                args = json.loads(args_str) if args_str else {}
                parse_error = ""
            except json.JSONDecodeError:
                args = {}
                parse_error = args_str
            tool_calls.append(
                ToolCall(
                    id=tc.get("id", "") if isinstance(tc, dict) else "",
                    name=func.get("name", "") if isinstance(func, dict) else "",
                    args=args,
                    parse_error=parse_error,
                )
            )
        usage = raw.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        return Reply(text=text, tool_calls=tool_calls, cached=cached, usage=usage, raw=raw)

    # -- chat --------------------------------------------------------------
    def _request(self, messages, tools, tool_choice, max_tokens) -> dict:
        """Talk to the server, retrying retryable failures. Always returns a plain dict."""
        retryable = tuple(getattr(self._openai, name) for name in _RETRYABLE)
        for attempt in range(self.max_retries + 1):
            try:
                kwargs = {
                    "model": self.settings.model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "max_tokens": max_tokens,
                    "seed": 0,
                }
                if tools is not None:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = tool_choice
                resp = self.client.chat.completions.create(**kwargs)
                return self._normalise(resp)
            except retryable:  # connection / timeout / 429 / 5xx
                if attempt >= self.max_retries:
                    raise
                time.sleep(2 ** attempt)
        # Unreachable: on the last attempt the retryable branch re-raises, so the
        # loop can only exit via `return`. Kept for type checkers.
        raise RuntimeError("unreachable: all LLM retries exhausted")

    def chat(self, messages, tools: list[dict] | None = None, *, tool_choice: str | dict = "auto",
             max_tokens: int = 1024) -> Reply:
        key = self._cache_key(messages, tools, tool_choice, max_tokens)

        if self._cache_enabled() and self.cache_dir is not None:
            cache_file = self.cache_dir / f"{key}.json"
            if cache_file.exists():
                raw = json.loads(cache_file.read_text(encoding="utf-8"))
                return self._build_reply(raw, cached=True)

        raw = self._request(messages, tools, tool_choice, max_tokens)

        if self._cache_enabled() and self.cache_dir is not None:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / f"{key}.json").write_text(
                json.dumps(raw, ensure_ascii=False, default=str), encoding="utf-8"
            )

        return self._build_reply(raw, cached=False)


class FakeLLM:
    """Scripted stand-in for :class:`LLM` with the same ``.chat`` signature.

    Takes a list of :class:`Reply` objects (or callables ``messages -> Reply``) and
    returns them in order. Records every call in ``.calls``. Raises ``RuntimeError``
    when it runs out. Used by tests of #13.
    """

    def __init__(self, replies) -> None:
        self._replies = list(replies)
        self.calls: list[dict] = []

    def chat(self, messages, tools: list[dict] | None = None, *, tool_choice: str | dict = "auto",
             max_tokens: int = 1024) -> Reply:
        self.calls.append(
            {"messages": messages, "tools": tools, "tool_choice": tool_choice, "max_tokens": max_tokens}
        )
        if not self._replies:
            raise RuntimeError("FakeLLM exhausted")
        reply = self._replies.pop(0)
        if callable(reply):
            return reply(messages)
        return reply
