"""Unit tests for discount-strategy-agent util.py."""
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

    def test_timeout_error_is_retryable(self):
        from util import _is_retryable_error
        assert _is_retryable_error(TimeoutError("timeout")) is True

    def test_http_500_is_retryable(self):
        from util import _is_retryable_error
        resp = MagicMock()
        resp.status_code = 500
        exc = httpx.HTTPStatusError("server error", request=MagicMock(), response=resp)
        assert _is_retryable_error(exc) is True

    def test_http_503_is_retryable(self):
        from util import _is_retryable_error
        resp = MagicMock()
        resp.status_code = 503
        exc = httpx.HTTPStatusError("unavailable", request=MagicMock(), response=resp)
        assert _is_retryable_error(exc) is True

    def test_http_400_not_retryable(self):
        from util import _is_retryable_error
        resp = MagicMock()
        resp.status_code = 400
        exc = httpx.HTTPStatusError("bad request", request=MagicMock(), response=resp)
        assert _is_retryable_error(exc) is False

    def test_http_404_not_retryable(self):
        from util import _is_retryable_error
        resp = MagicMock()
        resp.status_code = 404
        exc = httpx.HTTPStatusError("not found", request=MagicMock(), response=resp)
        assert _is_retryable_error(exc) is False

    def test_exception_group_is_retryable(self):
        from util import _is_retryable_error
        eg = ExceptionGroup("eg", [ValueError("inner")])
        assert _is_retryable_error(eg) is True


# ---------------------------------------------------------------------------
# enhance_tool_description
# ---------------------------------------------------------------------------

class TestEnhanceToolDescription:
    def _make_tool(self, server_name="sap:s4:SD", description="Get sales orders", fragment_name=None):
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
        tool = self._make_tool(description="Simulate a sales order discount")
        result = enhance_tool_description(tool)
        assert "Simulate a sales order discount" in result

    def test_includes_fragment_name(self):
        from util import enhance_tool_description
        tool = self._make_tool(server_name="sap:s4:SD", fragment_name="s4-sd-server")
        result = enhance_tool_description(tool)
        assert "s4-sd-server" in result

    def test_uses_server_name_when_no_fragment(self):
        from util import enhance_tool_description
        tool = MagicMock(spec=["server_name", "description"])
        tool.server_name = "sd-server"
        tool.description = "My tool"
        result = enhance_tool_description(tool)
        assert "sd-server" in result

    def test_none_tool_returns_empty_string(self):
        from util import enhance_tool_description
        result = enhance_tool_description(None)
        assert result == ""

    def test_none_description_handled(self):
        from util import enhance_tool_description
        tool = self._make_tool(description=None, fragment_name="label")
        result = enhance_tool_description(tool)
        assert isinstance(result, str)


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
        tool = self._make_tool("sap:s4:SD", "get_sales_orders")
        result = enhance_tool_name(tool)
        assert "SD" in result or "sd" in result.lower()
        assert "get_sales_orders" in result

    def test_special_chars_replaced_with_underscore(self):
        from util import enhance_tool_name
        tool = self._make_tool("sap:s4:SD.SALES", "my-tool")
        result = enhance_tool_name(tool)
        import re
        assert re.match(r"^[a-zA-Z0-9\-_]+$", result)

    def test_long_name_truncated_to_64(self):
        from util import enhance_tool_name
        tool = self._make_tool("sap:s4:" + "X" * 60, "Y" * 20)
        result = enhance_tool_name(tool)
        assert len(result) <= 64

    def test_short_name_not_truncated(self):
        from util import enhance_tool_name
        tool = self._make_tool("sap:s4:SD", "get_orders")
        result = enhance_tool_name(tool)
        assert len(result) <= 64
        assert "get_orders" in result

    def test_simulate_tool_name(self):
        from util import enhance_tool_name
        tool = self._make_tool("sap:s4:SD_0001", "simulate_sales_order")
        result = enhance_tool_name(tool)
        assert "simulate_sales_order" in result

    def test_three_segment_server(self):
        from util import enhance_tool_name
        tool = self._make_tool("sap:s4:CE_SD_0001", "get_pricing")
        result = enhance_tool_name(tool)
        assert "get_pricing" in result


# ---------------------------------------------------------------------------
# call_mcp_tool_with_retry
# ---------------------------------------------------------------------------

class TestCallMcpToolWithRetry:
    def _make_mcp_tool(self, name="get_sales_orders"):
        t = MagicMock()
        t.name = name
        return t

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        from util import call_mcp_tool_with_retry
        agw = AsyncMock()
        agw.call_mcp_tool = AsyncMock(return_value='{"sales_orders": []}')
        tool = self._make_mcp_tool()
        result = await call_mcp_tool_with_retry(agw, tool, user_token="tok")
        assert "sales_orders" in result

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
        agw.call_mcp_tool = AsyncMock(return_value="A" * 500)
        tool = self._make_mcp_tool()
        result = await call_mcp_tool_with_retry(agw, tool)
        assert "[truncated]" in result
        assert len(result) < 500

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
                raise RuntimeError("transient S/4 error")
            return '{"success": true}'

        agw.call_mcp_tool = flaky
        tool = self._make_mcp_tool()
        result = await call_mcp_tool_with_retry(agw, tool)
        assert '"success": true' in result
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
            return "result"

        agw.call_mcp_tool = capture_call
        tool = self._make_mcp_tool()
        await call_mcp_tool_with_retry(agw, tool, user_token="sales-token")
        assert captured.get("user_token") == "sales-token"

    @pytest.mark.asyncio
    async def test_omits_user_token_when_none(self):
        from util import call_mcp_tool_with_retry
        agw = AsyncMock()
        captured = {}

        async def capture_call(**kwargs):
            captured.update(kwargs)
            return "result"

        agw.call_mcp_tool = capture_call
        tool = self._make_mcp_tool()
        await call_mcp_tool_with_retry(agw, tool, user_token=None)
        assert "user_token" not in captured

    @pytest.mark.asyncio
    async def test_simulate_tool_succeeds(self):
        from util import call_mcp_tool_with_retry
        agw = AsyncMock()
        mock_response = '{"simulation_result": {"margin_safe": true, "gross_margin_pct": 55.56}}'
        agw.call_mcp_tool = AsyncMock(return_value=mock_response)
        tool = self._make_mcp_tool("simulate_sales_order")
        result = await call_mcp_tool_with_retry(
            agw, tool,
            user_token="tok",
            customer_id="C1000",
            material_id="MAT001",
            proposed_discount_pct=10.0
        )
        assert "margin_safe" in result
