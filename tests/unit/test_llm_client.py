from types import SimpleNamespace

import groq
import httpx
import pytest

from forest_bot.llm.client import LLMBadResponseError, LLMBusyError, LLMClient, parse_json_object


def _completion(content: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.fixture
def client(mocker):
    llm = LLMClient("test-key")
    create = mocker.AsyncMock()
    mocker.patch.object(llm._client.chat.completions, "create", create)
    return llm, create


def test_parse_plain_json():
    assert parse_json_object('{"answer": "так", "used": [1]}') == {"answer": "так", "used": [1]}


def test_parse_fenced_json():
    assert parse_json_object('```json\n{"place": null}\n```') == {"place": None}


@pytest.mark.parametrize("content", ["", "не JSON", "[1, 2]"])
def test_parse_rejects_non_objects(content):
    with pytest.raises(LLMBadResponseError):
        parse_json_object(content)


async def test_complete_json_uses_json_mode_and_low_reasoning(client):
    llm, create = client
    create.return_value = _completion('{"ok": true}')

    assert await llm.complete_json("openai/gpt-oss-20b", "system", "user") == {"ok": True}
    kwargs = create.call_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["reasoning_effort"] == "low"
    assert kwargs["messages"][0] == {"role": "system", "content": "system"}


async def test_complete_json_retries_once_on_bad_json(client):
    llm, create = client
    create.side_effect = [_completion("ой"), _completion('{"ok": 1}')]
    assert await llm.complete_json("m", "s", "u") == {"ok": 1}
    assert create.call_count == 2


async def test_complete_json_gives_up_after_second_bad_reply(client):
    llm, create = client
    create.return_value = _completion("ой")
    with pytest.raises(LLMBadResponseError):
        await llm.complete_json("m", "s", "u")


async def test_rate_limit_becomes_busy_error(client):
    # The SDK has already retried with retry-after by the time it raises
    llm, create = client
    response = httpx.Response(429, request=httpx.Request("POST", "https://api.groq.com"))
    create.side_effect = groq.RateLimitError("rate limited", response=response, body=None)
    with pytest.raises(LLMBusyError):
        await llm.complete_json("m", "s", "u")
