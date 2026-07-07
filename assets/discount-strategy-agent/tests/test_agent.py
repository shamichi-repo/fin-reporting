"""Unit tests for discount-strategy-agent agent.py."""
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


def _make_graph(final_content: str = "Here are your discount recommendations."):
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

    def test_get_system_prompt_mentions_discount(self):
        from agent import get_system_prompt
        prompt = get_system_prompt()
        assert "discount" in prompt.lower()

    def test_get_system_prompt_mentions_margin_floor(self):
        from agent import get_system_prompt
        prompt = get_system_prompt()
        assert "15%" in prompt or "15 percent" in prompt.lower() or "margin" in prompt.lower()

    def test_get_system_prompt_mentions_milestones(self):
        from agent import get_system_prompt
        prompt = get_system_prompt()
        for milestone in ["M1", "M2", "M3", "M4", "M5"]:
            assert milestone in prompt

    def test_get_system_prompt_mentions_sd_tools(self):
        from agent import get_system_prompt
        prompt = get_system_prompt()
        assert "get_sales_orders" in prompt or "sales order" in prompt.lower()

    def test_get_system_prompt_mentions_simulation(self):
        from agent import get_system_prompt
        prompt = get_system_prompt()
        assert "simulat" in prompt.lower()


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

    def test_llm_constructed(self, mock_llm, mock_summarization_middleware):
        from agent import SampleAgent
        agent = SampleAgent()
        mock_llm.assert_called_once()


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

    def test_multiple_threads_eviction(self, sample_agent):
        now = time.monotonic()
        sample_agent._last_active["stale-1"] = now - 5000
        sample_agent._last_active["stale-2"] = now - 6000
        sample_agent._last_active["fresh"] = now - 60
        sample_agent._checkpointer.delete_thread = MagicMock()
        sample_agent._touch("new")
        assert "stale-1" not in sample_agent._last_active
        assert "stale-2" not in sample_agent._last_active
        assert "fresh" in sample_agent._last_active


# ---------------------------------------------------------------------------
# stream()
# ---------------------------------------------------------------------------

class TestStream:
    @pytest.mark.asyncio
    async def test_stream_yields_processing_first(self, sample_agent, mock_create_agent):
        tool = MagicMock()
        tool.name = "get_sales_orders"
        chunks = []
        async for chunk in sample_agent.stream("Suggest discounts for C1000", "t1", tools=[tool]):
            chunks.append(chunk)
        assert chunks[0]["content"] == "Processing..."
        assert chunks[0]["is_task_complete"] is False

    @pytest.mark.asyncio
    async def test_stream_yields_final_response(self, sample_agent, mock_create_agent):
        mock_create_agent.return_value = _make_graph("I recommend a 10% discount, margin is 55%.")
        tool = MagicMock()
        tool.name = "get_sales_orders"
        chunks = []
        async for chunk in sample_agent.stream("Suggest discounts for C1000", "t1", tools=[tool]):
            chunks.append(chunk)
        final = chunks[-1]
        assert final["is_task_complete"] is True
        assert "10%" in final["content"]

    @pytest.mark.asyncio
    async def test_stream_no_tools_still_works(self, sample_agent, mock_create_agent):
        chunks = []
        async for chunk in sample_agent.stream("Suggest discounts", "t-no-tools", tools=[]):
            chunks.append(chunk)
        assert len(chunks) >= 2
        assert chunks[-1]["is_task_complete"] is True

    @pytest.mark.asyncio
    async def test_stream_handles_exception_gracefully(self, sample_agent, mock_create_agent):
        mock_create_agent.return_value.ainvoke = AsyncMock(
            side_effect=RuntimeError("S/4HANA unavailable")
        )
        chunks = []
        async for chunk in sample_agent.stream("get discounts", "t-err"):
            chunks.append(chunk)
        final = chunks[-1]
        assert final["is_task_complete"] is True
        assert "error" in final["content"].lower()

    @pytest.mark.asyncio
    async def test_stream_uses_context_id_as_thread_id(self, sample_agent, mock_create_agent):
        async for _ in sample_agent.stream("q", "sales-context-123"):
            pass
        call_args = mock_create_agent.return_value.ainvoke.call_args
        config = call_args[0][1] if call_args[0] else call_args[1].get("config", {})
        assert config.get("configurable", {}).get("thread_id") == "sales-context-123"

    @pytest.mark.asyncio
    async def test_stream_passes_tools_to_graph(self, sample_agent, mock_create_agent):
        tool1 = MagicMock()
        tool1.name = "get_sales_orders"
        tool2 = MagicMock()
        tool2.name = "simulate_sales_order"
        async for _ in sample_agent.stream("q", "t1", tools=[tool1, tool2]):
            pass
        _, kwargs = mock_create_agent.call_args
        assert tool1 in kwargs.get("tools", [])
        assert tool2 in kwargs.get("tools", [])

    @pytest.mark.asyncio
    async def test_stream_yields_exactly_two_chunks_on_success(self, sample_agent, mock_create_agent):
        chunks = []
        async for chunk in sample_agent.stream("q", "t1"):
            chunks.append(chunk)
        assert len(chunks) == 2
        assert not chunks[0]["is_task_complete"]
        assert chunks[1]["is_task_complete"]


# ---------------------------------------------------------------------------
# invoke()
# ---------------------------------------------------------------------------

class TestInvoke:
    @pytest.mark.asyncio
    async def test_invoke_returns_completed_status(self, sample_agent, mock_create_agent):
        mock_create_agent.return_value = _make_graph("10% discount approved, margin 55%.")
        result = await sample_agent.invoke("discount for C1000", "t2")
        assert result.status == "completed"
        assert "55%" in result.message

    @pytest.mark.asyncio
    async def test_invoke_returns_error_status_on_exception(self, sample_agent, mock_create_agent):
        mock_create_agent.return_value.ainvoke = AsyncMock(
            side_effect=ConnectionError("S/4 down")
        )
        result = await sample_agent.invoke("fail query", "t-fail")
        assert result.status == "completed"
        assert "error" in result.message.lower()

    @pytest.mark.asyncio
    async def test_invoke_passes_tools(self, sample_agent, mock_create_agent):
        tool = MagicMock()
        tool.name = "get_pricing_conditions"
        await sample_agent.invoke("price check", "t3", tools=[tool])
        _, kwargs = mock_create_agent.call_args
        assert tool in kwargs.get("tools", [])

    @pytest.mark.asyncio
    async def test_invoke_with_none_tools(self, sample_agent, mock_create_agent):
        result = await sample_agent.invoke("count", "t4", tools=None)
        assert result.status == "completed"

    @pytest.mark.asyncio
    async def test_invoke_with_all_four_sd_tools(self, sample_agent, mock_create_agent):
        tools = []
        for name in ["get_sales_orders", "get_pricing_conditions", "get_sales_price", "simulate_sales_order"]:
            t = MagicMock()
            t.name = name
            tools.append(t)
        result = await sample_agent.invoke("full discount analysis for C1000", "t5", tools=tools)
        assert result.status == "completed"


# ---------------------------------------------------------------------------
# AgentResponse dataclass
# ---------------------------------------------------------------------------

class TestAgentResponse:
    def test_completed_response(self):
        from agent import AgentResponse
        r = AgentResponse(status="completed", message="Discount 10% approved")
        assert r.status == "completed"
        assert "10%" in r.message

    def test_input_required_response(self):
        from agent import AgentResponse
        r = AgentResponse(status="input_required", message="Which customer?")
        assert r.status == "input_required"

    def test_error_response(self):
        from agent import AgentResponse
        r = AgentResponse(status="error", message="S/4HANA unavailable")
        assert r.status == "error"

    def test_thread_ttl_constant(self):
        from agent import THREAD_TTL_SECONDS
        assert THREAD_TTL_SECONDS == 3600
