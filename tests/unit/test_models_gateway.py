# SPDX-License-Identifier: Apache-2.0
"""The gateway's model routes: only inference, the real credential added outside, hosted
tools refused in the provider's own shape, and usage read from whole and streamed answers."""

from __future__ import annotations

import json

from mirrordimensions.network.payloads import models as m

ANTHROPIC = m.Route(provider="anthropic", credential="sk-real")
OPENAI = m.Route(provider="openai", credential="sk-real")


def test_only_inference_paths_are_forwarded() -> None:
    assert m.is_inference(ANTHROPIC, "POST", "/v1/messages")
    assert m.is_inference(ANTHROPIC, "post", "/v1/messages/count_tokens?beta=true")
    assert not m.is_inference(ANTHROPIC, "POST", "/v1/files")
    assert not m.is_inference(ANTHROPIC, "GET", "/v1/organizations/me")
    assert m.is_inference(OPENAI, "POST", "/v1/responses")
    assert not m.is_inference(OPENAI, "POST", "/v1/fine_tuning/jobs")
    status, _, body = m.not_inference("anthropic", "POST", "/v1/files")
    assert status == 404
    assert json.loads(body) == {
        "type": "error",
        "error": {"type": "not_found_error", "message": "Not Found"},
    }
    assert (
        json.loads(m.not_inference("openai", "POST", "/v1/files?x=1")[2])["error"]["message"]
        == "Invalid URL (POST /v1/files)"
    )


def test_the_placeholder_is_replaced_by_the_real_credential() -> None:
    sent = [
        ("Host", "api.anthropic.com"),
        ("x-api-key", "placeholder"),
        ("anthropic-version", "2023-06-01"),
    ]
    assert m.credential_headers(ANTHROPIC, sent) == [
        ("Host", "api.anthropic.com"),
        ("anthropic-version", "2023-06-01"),
        ("x-api-key", "sk-real"),
    ]
    bearer = [("Authorization", "Bearer placeholder"), ("Content-Type", "application/json")]
    assert m.credential_headers(OPENAI, bearer) == [
        ("Content-Type", "application/json"),
        ("authorization", "Bearer sk-real"),
    ]
    # Without a configured credential the request passes as sent (a self-hosted server
    # that needs none).
    assert m.credential_headers(m.Route(provider="self-hosted"), bearer) == bearer


def test_hosted_tools_are_found_by_type_and_by_field() -> None:
    body = json.dumps(
        {
            "tools": [
                {"type": "web_search_20260209", "name": "web_search"},
                {"type": "bash_20250124", "name": "bash"},
                {"name": "lookup_order", "input_schema": {"type": "object"}},
                {"type": "text_editor_20250728", "name": "str_replace_based_edit_tool"},
            ],
            "mcp_servers": [
                {"type": "url", "url": "https://mcp.vendor.example/sse", "name": "crm"}
            ],
        }
    ).encode()
    assert m.hosted_tools_in("anthropic", body) == ["web_search_20260209", "mcp_servers"]
    assert (
        m.hosted_tools_in(
            "anthropic",
            json.dumps({"tools": [{"type": "memory_20250818", "name": "memory"}]}).encode(),
        )
        == []
    )
    openai = json.dumps(
        {
            "tools": [
                {"type": "web_search_preview"},
                {"type": "function", "name": "f"},
                {"type": "mcp"},
            ]
        }
    ).encode()
    assert m.hosted_tools_in("openai", openai) == ["web_search_preview", "mcp"]
    assert (
        m.hosted_tools_in("openai", json.dumps({"web_search_options": {}}).encode()) == []
    )  # empty: off
    assert m.hosted_tools_in(
        "openai", json.dumps({"web_search_options": {"search_context_size": "low"}}).encode()
    ) == ["web_search_options"]
    assert m.hosted_tools_in("anthropic", b"not json") == []
    status, _, refused = m.refuse_hosted("anthropic", ["web_search_20260209"])
    assert status == 400
    assert json.loads(refused)["error"]["type"] == "invalid_request_error"


def test_usage_from_a_whole_answer_and_from_a_stream() -> None:
    whole = json.dumps(
        {"model": "claude-opus-5-5", "usage": {"input_tokens": 12, "output_tokens": 40}}
    ).encode()
    assert m.usage("anthropic", whole, streamed=False) == {
        "model": "claude-opus-5-5",
        "input_tokens": 12,
        "output_tokens": 40,
    }
    stream = (
        b"event: message_start\n"
        b'data: {"type":"message_start","message":{"model":"claude-opus-5-5","usage":{"input_tokens":12,"output_tokens":1}}}\n\n'
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}\n\n'
        b"event: message_delta\n"
        b'data: {"type":"message_delta","usage":{"output_tokens":40}}\n\n'
    )
    assert m.usage("anthropic", stream, streamed=True) == {
        "model": "claude-opus-5-5",
        "input_tokens": 12,
        "output_tokens": 40,
    }
    chat = 'data: {"model":"llama-3","choices":[]}\n\ndata: {"usage":{"prompt_tokens":5,"completion_tokens":9}}\n\ndata: [DONE]\n\n'
    assert m.usage("self-hosted", chat.encode(), streamed=True) == {
        "model": "llama-3",
        "input_tokens": 5,
        "output_tokens": 9,
    }
