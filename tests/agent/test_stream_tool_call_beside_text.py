"""A held SSE-looking content prefix must not discard a tool call on that chunk.

The first content token ``I`` is a prefix of the SSE field ``id``. While that
text was held, the chunk that resolved the hold used to ``continue`` past
``tool_calls``. A web turn then streamed prose and recorded zero tool events.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _chunk(content=None, tool_calls=None, finish_reason=None, model=None, usage=None):
    delta = SimpleNamespace(
        content=content, tool_calls=tool_calls, reasoning_content=None, reasoning=None,
    )
    choice = SimpleNamespace(index=0, delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], model=model, usage=usage)


def _tool_delta(name, arguments):
    function = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=0, id="call_web", function=function)


@patch("run_agent.AIAgent._create_request_openai_client")
@patch("run_agent.AIAgent._close_request_openai_client")
def test_held_content_prefix_keeps_the_tool_call(_close, create):
    from run_agent import AIAgent

    chunks = [
        _chunk(content="I"),
        _chunk(
            content=" will read.",
            tool_calls=[_tool_delta("web_extract", '{"urls":["https://example.com"]}')],
        ),
        _chunk(finish_reason="tool_calls", model="test-model"),
        SimpleNamespace(
            choices=[], model=None,
            usage=SimpleNamespace(prompt_tokens=4, completion_tokens=2),
        ),
    ]
    client = MagicMock()
    client.chat.completions.create.return_value = iter(chunks)
    create.return_value = client
    agent = AIAgent(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        model="test/model",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    agent.api_mode = "chat_completions"
    agent._interrupt_requested = False

    response = agent._interruptible_streaming_api_call({})
    tool_call = response.choices[0].message.tool_calls[0]
    assert tool_call.function.name == "web_extract"
    assert "example.com" in tool_call.function.arguments
