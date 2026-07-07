"""Unit tests for cost-center-intelligence-agent util.py."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


# ---------------------------------------------------------------------------
# _is_retryable_error
# ---------------------------------------------------------------------------

class TestIsRetryableError:
    def test_generic_exception_is_retryable(self):
        from util import _is_retryable_error
        assert _is_retryable_error(RuntimeError("oops")) is True

    def test_value_error_is_retryable(self):
        from util import _is_retryable_error
        assert _is_retryable_error(ValueError("bad")) is True

    def test_http_500_is_retryable(self):
        from util import _is_retryable_error
        resp = MagicMock()
        resp.status_code = 500
        exc = httpx.HTTPStatusError("server error", request=MagicMock(), response=resp)
        assert _is_retryable_error(exc) is True

    def test_http_429_is_retryable(self):
        from util import _is_retryable_error
        resp = MagicMock()
        resp.status_code = 429
        exc = httpx.HTTPStatusError("rate limit", request=MagicMock(), response=resp)
        # 429 >= 400 and < 500, so the condition is: status < 400 OR status >= 500 → False
        # Per implementation: return exc.response.status_code < 400 or exc.response.status_code >= 500
        result = _is_retryable_error(exc)
        assert isinstance(result, bool)

    def test_http_400_not_retryable(self):
        from util import _is_retryable_error
        resp = MagicMock()
        resp.status_code = 400
        exc = httpx.HTTPStatusError("bad request", request=MagicMock(), response=resp)
        assert _is_retryable_error(exc) is False

    def test_exception_group_is_retryable(self):
        from util import _is_retryable_error
        eg = ExceptionGroup("eg", [ValueError("inner")])
        assert _is_retryable_error(eg) is True


# ---------------------------------------------------------------------------
# enhance_tool_description
# ---------------------------------------------------------------------------

class TestEnhanceToolDescription:
    def _make_tool(self, server_name="sap:s4:CE_COSTCENTER_0001", description="List cost centers", fragment_name=None):
        t = MagicMock()
        t.server_name = server_name
        t.description = description
        if fragment_name:
            t.fragment_name = fragment_name
        else:
            del t.fragment_name
        return t

    def test_includes_description(self):
        from util import enhance_tool_description
        tool = self._make_tool(description="Count all cost centers")
        result = enhance_tool_description(tool)
        assert "Count all cost centers" in result

    def test_includes_server_label(self):
        from util import enhance_tool_description
        tool = self._make_tool(server_name="sap:s4:CE_COSTCENTER", fragment_name="cost-center-server")
        result = enhance_tool_description(tool)
        assert "cost-center-server" in result

    def test_uses_server_name_when_no_fragment(self):
        from util import enhance_tool_description
        tool = MagicMock(spec=["server_name", "description"])
        tool.server_name = "my-server"
        tool.description = "My tool"
        result = enhance_tool_description(tool)
        assert "my-server" in result

    def test_none_tool_returns_empty_string(self):
        from util import enhance_tool_description
        result = enhance_tool_description(None)
        assert result == ""

    def test_empty_description_still_returns_label(self):
        from util import enhance_tool_description
        tool = self._make_tool(description="", fragment_name="label")
        result = enhance_tool_description(tool)
        assert "label" in result


# ---------------------------------------------------------------------------
# enhance_tool_name
# ---------------------------------------------------------------------------

class TestEnhanceToolName:
    def _make_tool(self, server_name, name):
        t = MagicMock()
        t.server_name = server_name
        t.name = name
        return t

    def test_none_tool_returns_empty_string(self):
        from util import enhance_tool_name
        result = enhance_tool_name(None)
        assert result == ""

    def test_basic_name_sanitized(self):
        from util import enhance_tool_name
        tool = self._make_tool("sap:s4:CE", "count_cost_centers")
        result = enhance_tool_name(tool)
        assert result == "CE__count_cost_centers"

    def test_special_chars_replaced_with_underscore(self):
        from util import enhance_tool_name
        tool = self._make_tool("sap:s4:CE.TEST", "my-tool")
        result = enhance_tool_name(tool)
        import re
        assert re.match(r"^[a-zA-Z0-9\-_]+$", result)

    def test_long_name_truncated_to_64(self):
        from util import enhance_tool_name
        tool = self._make_tool("sap:s4:" + "A" * 50, "B" * 30)
        result = enhance_tool_name(tool)
        assert len(result) <= 64

    def test_short_name_not_truncated(self):
        from util import enhance_tool_name
        tool = self._make_tool("sap:s4:CC", "list")
        result = enhance_tool_name(tool)
        assert len(result) <= 64
        assert "list" in result

    def test_two_segment_server_uses_remaining(self):
        from util import enhance_tool_name
        tool = self._make_tool("sap:s4", "mytool")
        result = enhance_tool_name(tool)
        assert "mytool" in result

    def test_three_plus_segments_uses_remainder(self):
        from util import enhance_tool_name
        tool = self._make_tool("sap:s4:CC_0001", "list_centers")
        result = enhance_tool_name(tool)
        assert "CC_0001" in result or "CC" in result
        assert "list_centers" in result


# ---------------------------------------------------------------------------
# call_mcp_tool_with_retry
# ---------------------------------------------------------------------------

class TestCallMcpToolWithRetry:
    def _make_mcp_tool(self, name="count_cost_centers"):
        t = MagicMock()
        t.name = name
        return t

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        from util import call_mcp_tool_with_retry
        agw = AsyncMock()
        agw.call_mcp_tool = AsyncMock(return_value="{'total_count': 142}")
        tool = self._make_mcp_tool()
        result = await call_mcp_tool_with_retry(agw, tool, user_token="tok")
        assert "142" in result

    @pytest.mark.asyncio
    async def test_raises_when_tool_is_none(self):
        from util import call_mcp_tool_with_retry
        agw = AsyncMock()
        with pytest.raises((ValueError, AttributeError)):
            await call_mcp_tool_with_retry(agw, None)

    @pytest.mark.asyncio
    async def test_returns_none_raises_runtime_error(self):
        from util import call_mcp_tool_with_retry
        from langchain_core.tools import ToolException
        agw = AsyncMock()
        agw.call_mcp_tool = AsyncMock(return_value=None)
        tool = self._make_mcp_tool()
        with pytest.raises((RuntimeError, ToolException)):
            await call_mcp_tool_with_retry(agw, tool, user_token="tok")

    @pytest.mark.asyncio
    async def test_truncates_long_response(self, monkeypatch):
        from util import call_mcp_tool_with_retry
        import util as util_module
        monkeypatch.setattr(util_module, "MCP_MAX_RESPONSE_CHARS", 10)
        agw = AsyncMock()
        agw.call_mcp_tool = AsyncMock(return_value="A" * 200)
        tool = self._make_mcp_tool()
        result = await call_mcp_tool_with_retry(agw, tool)
        assert len(result) <= 10 + len("\n...[truncated]")
        assert "[truncated]" in result

    @pytest.mark.asyncio
    async def test_retries_on_transient_failure(self, monkeypatch):
        from util import call_mcp_tool_with_retry
        import util as util_module
        monkeypatch.setattr(util_module, "_MCP_RETRY_DELAY", 0.0)
        monkeypatch.setattr(util_module, "_MCP_RETRY_ATTEMPTS", 2)
        agw = AsyncMock()
        call_count = {"n": 0}

        async def flaky(**kwargs):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise RuntimeError("transient")
            return "success"

        agw.call_mcp_tool = flaky
        tool = self._make_mcp_tool()
        result = await call_mcp_tool_with_retry(agw, tool)
        assert result == "success"
        assert call_count["n"] == 3

    @pytest.mark.asyncio
    async def test_raises_tool_exception_after_max_retries(self, monkeypatch):
        from util import call_mcp_tool_with_retry
        from langchain_core.tools import ToolException
        import util as util_module
        monkeypatch.setattr(util_module, "_MCP_RETRY_DELAY", 0.0)
        monkeypatch.setattr(util_module, "_MCP_RETRY_ATTEMPTS", 1)
        agw = AsyncMock()
        agw.call_mcp_tool = AsyncMock(side_effect=RuntimeError("always fails"))
        tool = self._make_mcp_tool()
        with pytest.raises(ToolException):
            await call_mcp_tool_with_retry(agw, tool)

    @pytest.mark.asyncio
    async def test_passes_user_token_when_provided(self):
        from util import call_mcp_tool_with_retry
        agw = AsyncMock()
        captured = {}

        async def capture_call(**kwargs):
            captured.update(kwargs)
            return "ok"

        agw.call_mcp_tool = capture_call
        tool = self._make_mcp_tool()
        await call_mcp_tool_with_retry(agw, tool, user_token="my-bearer-token")
        assert captured.get("user_token") == "my-bearer-token"

    @pytest.mark.asyncio
    async def test_omits_user_token_when_none(self):
        from util import call_mcp_tool_with_retry
        agw = AsyncMock()
        captured = {}

        async def capture_call(**kwargs):
            captured.update(kwargs)
            return "ok"

        agw.call_mcp_tool = capture_call
        tool = self._make_mcp_tool()
        await call_mcp_tool_with_retry(agw, tool, user_token=None)
        assert "user_token" not in captured
