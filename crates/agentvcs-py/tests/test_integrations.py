"""Model wrappers against local HTTP fakes only — no real model or API is called."""

import json

import pytest

import agentvcs as avcs
from agentvcs.integrations.anthropic import AnthropicClient
from agentvcs.integrations.openai_compat import OpenAICompatClient, OpenAICompatError
from agentvcs.testing import FakeAnthropicServer, FakeOpenAIServer
from conftest import manifest, supervise


def steps(run):
    return [e["body"] for e in run.log() if e["kind"] == "step"]


@pytest.fixture
def oai():
    with FakeOpenAIServer(lambda req: "four words of reply") as srv:
        yield srv


def test_openai_request_is_built_from_the_manifest(store, oai):
    client = OpenAICompatClient(oai.base_url)
    with avcs.run(manifest(), store=store, run_id="r") as run:
        c = client.complete("x", {"doc": "the contract"})
    (req,) = oai.requests
    assert req == {
        "model": "m-1",
        "messages": [{"role": "system", "content": "be brief"},
                     {"role": "user", "content": "Extract the contract"}],
        "temperature": 0.2, "max_tokens": 64, "seed": 7,  # grammar: null is not sent
    }
    assert c.text == "four words of reply" and c.tokens_out == 4 and c.tokens_in == 5
    (b,) = steps(run)  # outside a @step: one step of its own
    assert b["agent_id"] == "x" and b["tokens"] == {"in": 5, "out": 4}
    assert b["latency_ms"] > 0
    assert json.loads(run.get(b["inputs"][0])) == req  # the request is an input
    assert run.get(b["outputs"][0]) == b"four words of reply"


def test_openai_call_inside_a_step_adds_to_that_step(store, oai):
    client = OpenAICompatClient(oai.base_url)
    with avcs.run(manifest(), store=store) as run:

        @avcs.step("pipeline")
        def two_calls():
            client.complete("x", {"doc": "a"})
            client.complete("x", {"doc": "b"})

        two_calls()
    (b,) = steps(run)
    assert b["agent_id"] == "pipeline" and b["tokens"] == {"in": 8, "out": 8}
    assert len(b["inputs"]) == 2 and len(b["outputs"]) == 2


def test_a_patch_changes_the_next_request(store, oai):
    client = OpenAICompatClient(oai.base_url)
    with avcs.run(manifest(), store=store, run_id="r") as run:
        client.complete("x", {"doc": "a"})
        supervise(store, "r", manifest(model="m-2", temperature=0.0, template="List every field of {doc}"))
        client.complete("x", {"doc": "a"})
    first, second = oai.requests
    assert (first["model"], first["temperature"]) == ("m-1", 0.2)
    assert (second["model"], second["temperature"]) == ("m-2", 0.0)
    assert second["messages"][1]["content"] == "List every field of a"
    a, b = steps(run)
    assert a["manifest_id"] != b["manifest_id"] == run.manifest.id


def test_outside_a_run_needs_an_explicit_manifest_and_records_nothing(store, oai):
    client = OpenAICompatClient(oai.base_url)
    with pytest.raises(RuntimeError, match="manifest"):
        client.complete("x", {"doc": "a"})
    run = avcs.run(manifest(), store=store).start()
    c = client.complete("x", {"doc": "a"}, manifest=run.manifest)
    assert c.manifest_id == run.manifest.id
    assert steps(run) == []


def test_missing_prompt_variable_is_an_error(store, oai):
    client = OpenAICompatClient(oai.base_url)
    with avcs.run(manifest(), store=store):
        with pytest.raises(KeyError, match="doc"):
            client.complete("x", {})
    assert oai.requests == []


def test_http_error_raises_and_records_no_step(store):
    with FakeOpenAIServer(lambda r: "x", status=500) as srv:
        client = OpenAICompatClient(srv.base_url, api_key="test-key")
        with pytest.raises(OpenAICompatError, match="500"):
            with avcs.run(manifest(), store=store) as run:
                client.complete("x", {"doc": "a"})
        assert srv.headers[0]["authorization"] == "Bearer test-key"
    assert steps(run) == []


def claude_manifest(**sampling):
    return {
        "protocol": "agentvcs/0.1", "type": "harness_manifest",
        "dimensions": {
            "s.prompt": {"kind": "prompt", "content": {"template": "Summarize: {doc}", "variables": ["doc"], "system": "One sentence."}},
            "s.model": {"kind": "model", "content": {"provider": "anthropic", "id": "claude-opus-5-5"}},
            "s.sampling": {"kind": "sampling", "content": sampling},
        },
    }


def test_anthropic_sdk_against_a_local_fake(store):
    anthropic = pytest.importorskip("anthropic")
    with FakeAnthropicServer(lambda req: "A short summary.") as srv:
        sdk = anthropic.Anthropic(base_url=srv.base_url, api_key="test-key", max_retries=0)
        client = AnthropicClient(sdk)
        m = claude_manifest(max_tokens=512, output_config={"effort": "low"}, stop=["\n\n"],
                            seed=3, grammar="root ::= x")
        with avcs.run(m, store=store, run_id="r") as run:
            c = client.complete("s", {"doc": "the contract"})
        (req,) = srv.requests
        assert srv.headers[0]["x-api-key"] == "test-key"
    assert req == {
        "model": "claude-opus-5-5", "max_tokens": 512, "system": "One sentence.",
        "messages": [{"role": "user", "content": "Summarize: the contract"}],
        "stop_sequences": ["\n\n"], "output_config": {"effort": "low"},
    }  # seed / grammar are local-server fields and are dropped
    assert (c.text, c.tokens_in, c.tokens_out, c.stop_reason) == ("A short summary.", 5, 3, "end_turn")  # 3 user + 2 system words
    (b,) = steps(run)
    assert b["tokens"] == {"in": 5, "out": 3} and b["agent_id"] == "s"


def test_anthropic_wrapper_with_a_duck_typed_client(store):
    class Usage:
        input_tokens, output_tokens = 11, 2

    class Block:
        type, text = "text", "ok"

    class Resp:
        content, usage, stop_reason = [Block()], Usage(), "end_turn"

    class Messages:
        def __init__(self):
            self.calls = []

        def create(self, **kw):
            self.calls.append(kw)
            return Resp()

    class Fake:
        messages = Messages()

    fake = Fake()
    with avcs.run(claude_manifest(), store=store) as run:

        @avcs.step("summarizer")
        def summarize():
            return AnthropicClient(fake).complete("s", {"doc": "d"}).text

        assert summarize() == "ok"
    assert fake.messages.calls[0]["max_tokens"] == 16000
    (b,) = steps(run)
    assert b["tokens"] == {"in": 11, "out": 2}
