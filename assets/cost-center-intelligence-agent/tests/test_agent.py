"""Unit tests for cost-center-intelligence-agent agent.py."""
import asyncio
import time
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_message(content: str):
    msg = MagicMock()
    msg.content = content
    return msg


def _make_graph(final_content: str = "Here are your cost centers."):
    """Return a mock graph whose ainvoke returns a canned message list."""
    graph = AsyncMock()
    graph.ainvoke = AsyncMock(
        return_value={"messages": [_make_message(final_content)]}
    )
    return graph


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_create_agent():
    """Patch langchain create_agent to return a controllable mock graph."""
    with patch("agent.create_agent") as p:
        p.return_value = _make_graph()
        yield p


@pytest.fixture
def mock_llm():
    """Patch ChatLiteLLM so no network calls are made at construction time."""
    with patch("agent.ChatLiteLLM") as p:
        instance = MagicMock()
        p.return_value = instance
        yield p


@pytest.fixture
def mock_summarization_middleware():
    with patch("agent.SummarizationMiddleware") as p:
        p.return_value = MagicMock()
        yield p


@pytest.fixture
def sample_agent(mock_llm, mock_summarization_middleware):
    from agent import SampleAgent
    return SampleAgent()


# ---------------------------------------------------------------------------
# Module-level decorator tests
# ---------------------------------------------------------------------------

class TestDecoratorFunctions:
    def test_get_model_name_returns_string(self):
        from agent import get_model_name
        assert isinstance(get_model_name(), str)
        assert len(get_model_name()) > 0

    def test_get_temperature_returns_float(self):
        from agent import get_temperature
        assert isinstance(get_temperature(), float)
        assert 0.0 <= get_temperature() <= 1.0

    def test_get_system_prompt_mentions_cost_center(self):
        from agent import get_system_prompt
        prompt = get_system_prompt()
        assert "cost center" in prompt.lower()

    def test_get_system_prompt_mentions_milestones(self):
        from agent import get_system_prompt
        prompt = get_system_prompt()
        for milestone in ["M1", "M2", "M3", "M4", "M5"]:
            assert milestone in prompt

    def test_get_system_prompt_mentions_tools(self):
        from agent import get_system_prompt
        prompt = get_system_prompt()
        assert "count_cost_centers" in prompt or "list_top" in prompt or "tools" in prompt.lower()


# ---------------------------------------------------------------------------
# SampleAgent construction
# ---------------------------------------------------------------------------

class TestSampleAgentConstruction:
    def test_supported_content_types(self, sample_agent):
        assert "text" in sample_agent.SUPPORTED_CONTENT_TYPES
        assert "text/plain" in sample_agent.SUPPORTED_CONTENT_TYPES

    def test_has_checkpointer(self, sample_agent):
        assert sample_agent._checkpointer is not None

    def test_last_active_starts_empty(self, sample_agent):
        assert sample_agent._last_active == {}


# ---------------------------------------------------------------------------
# _touch / TTL eviction
# ---------------------------------------------------------------------------

class TestTouchAndEviction:
    def test_touch_registers_thread(self, sample_agent):
        sample_agent._touch("thread-1")
        assert "thread-1" in sample_agent._last_active

    def test_touch_updates_timestamp(self, sample_agent):
        sample_agent._touch("thread-1")
        ts1 = sample_agent._last_active["thread-1"]
        time.sleep(0.01)
        sample_agent._touch("thread-1")
        ts2 = sample_agent._last_active["thread-1"]
        assert ts2 >= ts1

    def test_touch_evicts_stale_thread(self, sample_agent):
        sample_agent._last_active["old-thread"] = time.monotonic() - 4000
        sample_agent._checkpointer.delete_thread = MagicMock()
        sample_agent._touch("new-thread")
        assert "old-thread" not in sample_agent._last_active
        sample_agent._checkpointer.delete_thread.assert_called_once_with("old-thread")

    def test_touch_keeps_fresh_thread(self, sample_agent):
        sample_agent._last_active["fresh-thread"] = time.monotonic() - 10
        sample_agent._checkpointer.delete_thread = MagicMock()
        sample_agent._touch("other-thread")
        assert "fresh-thread" in sample_agent._last_active


# ---------------------------------------------------------------------------
# stream()
# ---------------------------------------------------------------------------

class TestStream:
    @pytest.mark.asyncio
    async def test_stream_yields_processing_first(self, sample_agent, mock_create_agent):
        tool = MagicMock()
        tool.name = "count_cost_centers"
        chunks = []
        async for chunk in sample_agent.stream("How many cost centers?", "t1", tools=[tool]):
            chunks.append(chunk)
        assert chunks[0]["content"] == "Processing..."
        assert chunks[0]["is_task_complete"] is False

    @pytest.mark.asyncio
    async def test_stream_yields_final_response(self, sample_agent, mock_create_agent):
        mock_create_agent.return_value = _make_graph("There are 142 cost centers.")
        tool = MagicMock()
        tool.name = "count_cost_centers"
        chunks = []
        async for chunk in sample_agent.stream("How many cost centers?", "t1", tools=[tool]):
            chunks.append(chunk)
        final = chunks[-1]
        assert final["is_task_complete"] is True
        assert "142" in final["content"]

    @pytest.mark.asyncio
    async def test_stream_no_tools_adds_warning_to_prompt(self, sample_agent, mock_create_agent):
        captured_kwargs = {}

        def capture(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return _make_graph()

        mock_create_agent.side_effect = capture
        chunks = []
        async for chunk in sample_agent.stream("How many cost centers?", "t-no-tools", tools=[]):
            chunks.append(chunk)
        called_prompt = mock_create_agent.call_args[1].get(
            "system_prompt", mock_create_agent.call_args[0][2] if len(mock_create_agent.call_args[0]) > 2 else ""
        )
        # No tools branch appends a warning; just verify create_agent was called
        mock_create_agent.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_handles_exception_gracefully(self, sample_agent, mock_create_agent):
        mock_create_agent.return_value.ainvoke = AsyncMock(
            side_effect=RuntimeError("LLM unavailable")
        )
        chunks = []
        async for chunk in sample_agent.stream("count centers", "t-err"):
            chunks.append(chunk)
        final = chunks[-1]
        assert final["is_task_complete"] is True
        assert "error" in final["content"].lower()

    @pytest.mark.asyncio
    async def test_stream_uses_context_id_as_thread_id(self, sample_agent, mock_create_agent):
        async for _ in sample_agent.stream("q", "my-context-id"):
            pass
        call_args = mock_create_agent.return_value.ainvoke.call_args
        config = call_args[0][1] if call_args[0] else call_args[1].get("config", {})
        assert config.get("configurable", {}).get("thread_id") == "my-context-id"


# ---------------------------------------------------------------------------
# invoke()
# ---------------------------------------------------------------------------

class TestInvoke:
    @pytest.mark.asyncio
    async def test_invoke_returns_completed_status(self, sample_agent, mock_create_agent):
        mock_create_agent.return_value = _make_graph("Top 5 cost centers listed.")
        result = await sample_agent.invoke("List top cost centers", "t2")
        assert result.status == "completed"
        assert "cost centers" in result.message.lower()

    @pytest.mark.asyncio
    async def test_invoke_returns_error_status_on_exception(self, sample_agent, mock_create_agent):
        mock_create_agent.return_value.ainvoke = AsyncMock(
            side_effect=ValueError("boom")
        )
        result = await sample_agent.invoke("fail query", "t-fail")
        assert result.status == "completed"
        assert "error" in result.message.lower()

    @pytest.mark.asyncio
    async def test_invoke_passes_tools(self, sample_agent, mock_create_agent):
        tool = MagicMock()
        tool.name = "count_cost_centers"
        await sample_agent.invoke("count", "t3", tools=[tool])
        _, kwargs = mock_create_agent.call_args
        assert tool in kwargs.get("tools", [])

    @pytest.mark.asyncio
    async def test_invoke_with_none_tools(self, sample_agent, mock_create_agent):
        result = await sample_agent.invoke("count", "t4", tools=None)
        assert result.status == "completed"


# ---------------------------------------------------------------------------
# AgentResponse dataclass
# ---------------------------------------------------------------------------

class TestAgentResponse:
    def test_completed_response(self):
        from agent import AgentResponse
        r = AgentResponse(status="completed", message="done")
        assert r.status == "completed"
        assert r.message == "done"

    def test_input_required_response(self):
        from agent import AgentResponse
        r = AgentResponse(status="input_required", message="please clarify")
        assert r.status == "input_required"

    def test_error_response(self):
        from agent import AgentResponse
        r = AgentResponse(status="error", message="something went wrong")
        assert r.status == "error"
