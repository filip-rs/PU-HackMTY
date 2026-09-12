"""Tests for the LLM client and config (issue #22).

All tests are network-free — CI has no `.env` and never touches the cluster
(AGENTS.md rule 8). The only network test is gated behind ``@pytest.mark.llm`` and
auto-skips. A stub with the same ``client.chat.completions.create(**kw)`` shape
stands in for ``openai.OpenAI``.
"""
from __future__ import annotations

import json

import openai
import pytest

from agent.config import KEYS, Settings, load_env, settings
from agent.llm import (
    LLM,
    FakeLLM,
    Reply,
    ToolCall,
    assistant_message,
    tool_message,
)

ADD_TOOL = {
    "type": "function",
    "function": {
        "name": "add",
        "description": "Add two integers",
        "parameters": {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        },
    },
}


def chat_response(content=None, tool_calls=None, usage=None):
    message: dict = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-1",
        "choices": [{"message": message, "finish_reason": "stop"}],
        "usage": usage or {"prompt_tokens": 1, "completion_tokens": 2},
    }


class _Completions:
    """Mimics ``client.chat.completions``; pops responses, raising Exceptions verbatim."""

    def __init__(self, responses, factory=None):
        self._responses = list(responses)
        self._factory = factory
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self._responses:
            item = self._responses.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        if self._factory is not None:
            return self._factory(kwargs)
        raise AssertionError("stub exhausted")


class _ChatNS:
    def __init__(self, responses, factory=None):
        self.completions = _Completions(responses, factory)


class StubClient:
    def __init__(self, responses, factory=None):
        self.chat = _ChatNS(responses, factory)


def _settings():
    return Settings(base_url="https://x/v1", api_key="k", model="m")


# ---- config --------------------------------------------------------------

def test_load_env(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text("# a comment\n\nLLM_BASE_URL=https://a/v1\nLLM_API_KEY=\"secret key\"\nLLM_MODEL=model-1\n")
    env = load_env(p)
    assert env["LLM_BASE_URL"] == "https://a/v1"
    assert env["LLM_API_KEY"] == "secret key"
    assert env["LLM_MODEL"] == "model-1"
    monkeypatch.setenv("LLM_MODEL", "x")
    env2 = load_env(p)
    assert env2["LLM_MODEL"] == "x"
    assert "LLM_API_KEY" in KEYS


def test_settings_none_when_missing_key(tmp_path):
    p = tmp_path / ".env"
    p.write_text("LLM_BASE_URL=https://a/v1\n")
    assert settings(p) is None


def test_settings_parses(tmp_path):
    p = tmp_path / ".env"
    p.write_text("LLM_BASE_URL=https://a/v1\nLLM_API_KEY=abc\nLLM_MODEL=m1\n")
    s = settings(p)
    assert s is not None
    assert s.base_url == "https://a/v1"
    assert s.api_key == "abc"
    assert s.model == "m1"


# ---- tool-call parsing ---------------------------------------------------

def test_tool_calls_parsed():
    resp = chat_response(
        content=None,
        tool_calls=[{"id": "call_1", "type": "function",
                     "function": {"name": "get_supplier", "arguments": '{"supplier_id": "S00030"}'}}],
    )
    llm = LLM(_settings(), client=StubClient([resp]), cache_dir=None)
    reply = llm.chat([{"role": "user", "content": "hi"}], tools=[ADD_TOOL])
    assert len(reply.tool_calls) == 1
    assert reply.tool_calls[0].id == "call_1"
    assert reply.tool_calls[0].name == "get_supplier"
    assert reply.tool_calls[0].args == {"supplier_id": "S00030"}
    assert reply.tool_calls[0].parse_error == ""
    assert reply.text == ""
    assert reply.cached is False


def test_tool_call_bad_arguments():
    resp = chat_response(
        content=None,
        tool_calls=[{"id": "c", "type": "function",
                     "function": {"name": "f", "arguments": "{not json"}}],
    )
    llm = LLM(_settings(), client=StubClient([resp]), cache_dir=None)
    reply = llm.chat([{"role": "user", "content": "hi"}], tools=[ADD_TOOL])
    assert reply.tool_calls[0].args == {}
    assert reply.tool_calls[0].parse_error != ""


def test_content_only_reply():
    llm = LLM(_settings(), client=StubClient([chat_response(content="hello")]), cache_dir=None)
    reply = llm.chat([{"role": "user", "content": "hi"}])
    assert reply.tool_calls == []
    assert reply.text == "hello"
    assert reply.usage == {"prompt_tokens": 1, "completion_tokens": 2}


# ---- cache ---------------------------------------------------------------

def test_cache_hit_and_miss(tmp_path, monkeypatch):
    llm = LLM(_settings(), client=StubClient([], factory=lambda kw: chat_response(content="ok")),
              cache_dir=tmp_path)
    messages = [{"role": "user", "content": "hi"}]
    r1 = llm.chat(messages)
    assert r1.cached is False
    r2 = llm.chat(messages)
    assert r2.cached is True
    assert llm.client.chat.completions.calls == 1
    # different max_tokens -> different key -> cache miss
    r3 = llm.chat(messages, max_tokens=2048)
    assert r3.cached is False
    assert llm.client.chat.completions.calls == 2
    # LLM_CACHE=0 disables the cache entirely
    monkeypatch.setenv("LLM_CACHE", "0")
    r4 = llm.chat(messages)
    assert r4.cached is False
    assert llm.client.chat.completions.calls == 3


# ---- retries -------------------------------------------------------------

def test_retries_then_success(monkeypatch):
    monkeypatch.setattr("agent.llm.time.sleep", lambda s: None)
    err = openai.APIConnectionError(request=None)
    llm = LLM(_settings(), client=StubClient([err, err, chat_response(content="ok")]), cache_dir=None)
    reply = llm.chat([{"role": "user", "content": "hi"}])
    assert reply.text == "ok"
    assert llm.client.chat.completions.calls == 3


def test_retries_exhausted_propagates(monkeypatch):
    monkeypatch.setattr("agent.llm.time.sleep", lambda s: None)
    err = openai.APIConnectionError(request=None)
    llm = LLM(_settings(), client=StubClient([err, err, err, err]), cache_dir=None, max_retries=3)
    with pytest.raises(openai.APIConnectionError):
        llm.chat([{"role": "user", "content": "hi"}])
    assert llm.client.chat.completions.calls == 4


# ---- FakeLLM -------------------------------------------------------------

def test_fake_llm_sequence():
    r1 = Reply(text="a", tool_calls=[], cached=False, usage={}, raw={})
    r2 = Reply(text="b", tool_calls=[], cached=False, usage={}, raw={})
    fake = FakeLLM([r1, r2])
    assert fake.chat([{"role": "user", "content": "x"}]) is r1
    assert fake.chat([{"role": "user", "content": "x"}]) is r2
    assert len(fake.calls) == 2
    with pytest.raises(RuntimeError):
        fake.chat([{"role": "user", "content": "x"}])


def test_fake_llm_callable():
    fake = FakeLLM([lambda messages: Reply(text=messages[-1]["content"], tool_calls=[], cached=False,
                                           usage={}, raw={})])
    out = fake.chat([{"role": "user", "content": "yo"}])
    assert out.text == "yo"
    assert len(fake.calls) == 1


# ---- message helpers -----------------------------------------------------

def test_assistant_and_tool_messages():
    tc = ToolCall(id="call_1", name="get_supplier", args={"supplier_id": "S00030"})
    am = assistant_message(Reply(text="", tool_calls=[tc], cached=False, usage={}, raw={}))
    json.dumps(am)
    assert am["role"] == "assistant"
    assert am["tool_calls"][0]["id"] == "call_1"
    tm = tool_message(tc, {"supplier": "ok"})
    json.dumps(tm)
    assert tm["role"] == "tool"
    assert tm["tool_call_id"] == "call_1"
    assert tm["name"] == "get_supplier"


# ---- real endpoint (skipped without .env) --------------------------------

@pytest.mark.llm
def test_llm_real_round_trip():
    s = settings()
    if s is None:
        pytest.skip("no .env")
    llm = LLM(s)
    plain = llm.chat([{"role": "user", "content": "Reply with the single word OK."}], max_tokens=8)
    assert plain.text
    tools = llm.chat(
        [{"role": "user", "content": "Use the add tool to add 2 and 3."}],
        tools=[ADD_TOOL],
        max_tokens=64,
    )
    assert tools.tool_calls
    assert tools.tool_calls[0].name == "add"
    assert tools.tool_calls[0].args == {"a": 2, "b": 3}
