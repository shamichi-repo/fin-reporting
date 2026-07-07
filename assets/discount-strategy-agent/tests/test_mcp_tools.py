"""Unit tests for discount-strategy-agent mcp_tools.py."""
import asyncio
import json
import os
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# conftest.py already sets IBD_TESTING=1, so all tests run in mock mode


class TestBuildMockTools:
    def test_returns_list(self):
        from mcp_tools import _build_mock_tools
        tools = _build_mock_tools()
        assert isinstance(tools, list)

    def test_returns_correct_count(self):
        from mcp_tools import _build_mock_tools
        tools = _build_mock_tools()
        assert len(tools) == 4

    def test_tool_names(self):
        from mcp_tools import _build_mock_tools
        tools = _build_mock_tools()
        names = {t.name for t in tools}
        assert "get_sales_orders" in names
        assert "get_pricing_conditions" in names
        assert "get_sales_price" in names
        assert "simulate_sales_order" in names

    def test_tools_are_structured_tools(self):
        from mcp_tools import _build_mock_tools
        from langchain_core.tools import StructuredTool
        tools = _build_mock_tools()
        for t in tools:
            assert isinstance(t, StructuredTool)

    def test_tools_have_descriptions(self):
        from mcp_tools import _build_mock_tools
        tools = _build_mock_tools()
        for t in tools:
            assert t.description and len(t.description) > 0

    def test_all_tools_are_coroutines(self):
        from mcp_tools import _build_mock_tools
        tools = _build_mock_tools()
        for t in tools:
            assert t.coroutine is not None

    @pytest.mark.asyncio
    async def test_get_sales_orders_returns_mock_data(self):
        from mcp_tools import _build_mock_tools
        tools = _build_mock_tools()
        tool = next(t for t in tools if t.name == "get_sales_orders")
        result = await tool.coroutine(customer_id="C1000")
        data = json.loads(result)
        assert "sales_orders" in data
        assert data["total_count"] == 2

    @pytest.mark.asyncio
    async def test_get_pricing_conditions_returns_mock_data(self):
        from mcp_tools import _build_mock_tools
        tools = _build_mock_tools()
        tool = next(t for t in tools if t.name == "get_pricing_conditions")
        result = await tool.coroutine(customer_id="C1000")
        data = json.loads(result)
        assert "pricing_conditions" in data
        assert len(data["pricing_conditions"]) == 3

    @pytest.mark.asyncio
    async def test_get_sales_price_returns_mock_data(self):
        from mcp_tools import _build_mock_tools
        tools = _build_mock_tools()
        tool = next(t for t in tools if t.name == "get_sales_price")
        result = await tool.coroutine(material_id="MAT001")
        data = json.loads(result)
        assert "base_price" in data
        assert data["gross_margin_pct"] == 60.0

    @pytest.mark.asyncio
    async def test_simulate_sales_order_returns_mock_data(self):
        from mcp_tools import _build_mock_tools
        tools = _build_mock_tools()
        tool = next(t for t in tools if t.name == "simulate_sales_order")
        result = await tool.coroutine(
            customer_id="C1000", material_id="MAT001", proposed_discount_pct=10.0
        )
        data = json.loads(result)
        assert "simulation_result" in data
        assert data["simulation_result"]["margin_safe"] is True

    @pytest.mark.asyncio
    async def test_simulate_captures_margin_floor(self):
        from mcp_tools import _build_mock_tools
        tools = _build_mock_tools()
        tool = next(t for t in tools if t.name == "simulate_sales_order")
        result = await tool.coroutine(
            customer_id="C1000", material_id="MAT001", proposed_discount_pct=10.0
        )
        data = json.loads(result)
        assert data["simulation_result"]["margin_floor_pct"] == 15.0

    def test_missing_mock_file_returns_empty(self, tmp_path):
        import mcp_tools
        original = mcp_tools._MOCK_FILE
        mcp_tools._MOCK_FILE = tmp_path / "nonexistent.json"
        try:
            result = mcp_tools._build_mock_tools()
            assert result == []
        finally:
            mcp_tools._MOCK_FILE = original

    def test_invalid_json_returns_empty(self, tmp_path):
        import mcp_tools
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json {{{")
        original = mcp_tools._MOCK_FILE
        mcp_tools._MOCK_FILE = bad_file
        try:
            result = mcp_tools._build_mock_tools()
            assert result == []
        finally:
            mcp_tools._MOCK_FILE = original

    def test_empty_servers_returns_empty(self, tmp_path):
        import mcp_tools
        empty_file = tmp_path / "empty.json"
        empty_file.write_text('{"servers": {}}')
        original = mcp_tools._MOCK_FILE
        mcp_tools._MOCK_FILE = empty_file
        try:
            result = mcp_tools._build_mock_tools()
            assert result == []
        finally:
            mcp_tools._MOCK_FILE = original


class TestGetMcpTools:
    @pytest.mark.asyncio
    async def test_returns_list_in_test_mode(self):
        from mcp_tools import get_mcp_tools
        tools = await get_mcp_tools(None)
        assert isinstance(tools, list)
        assert len(tools) > 0

    @pytest.mark.asyncio
    async def test_returns_four_tools_in_test_mode(self):
        from mcp_tools import get_mcp_tools
        tools = await get_mcp_tools(None)
        assert len(tools) == 4

    @pytest.mark.asyncio
    async def test_token_ignored_in_test_mode(self):
        from mcp_tools import get_mcp_tools
        tools = await get_mcp_tools("any-token")
        assert len(tools) == 4

    @pytest.mark.asyncio
    async def test_returns_all_sd_tool_names(self):
        from mcp_tools import get_mcp_tools
        tools = await get_mcp_tools(None)
        names = {t.name for t in tools}
        assert "get_sales_orders" in names
        assert "simulate_sales_order" in names


class TestUserTokenContext:
    def test_set_and_get_user_token(self):
        from mcp_tools import set_user_token, get_user_token
        set_user_token("sales-rep-token")
        assert get_user_token() == "sales-rep-token"

    def test_set_none_token(self):
        from mcp_tools import set_user_token, get_user_token
        set_user_token(None)
        assert get_user_token() is None

    def test_set_token_returns_token_object(self):
        from mcp_tools import set_user_token
        result = set_user_token("token-abc")
        assert result is not None


class TestConvertMcpToolToLangchain:
    def _make_mcp_tool(self, name="get_sales_orders", description="Get orders", props=None, required=None):
        tool = MagicMock()
        tool.name = name
        tool.description = description
        tool.server_name = "sap:s4:SD"
        tool.fragment_name = "s4-sd-server"
        tool.input_schema = {
            "properties": props or {},
            "required": required or [],
        }
        return tool

    def test_returns_structured_tool(self):
        from mcp_tools import _convert_mcp_tool_to_langchain
        from langchain_core.tools import StructuredTool
        agw_client = AsyncMock()
        mcp_tool = self._make_mcp_tool()
        result = _convert_mcp_tool_to_langchain(mcp_tool, agw_client)
        assert isinstance(result, StructuredTool)

    def test_raises_on_none_tool(self):
        from mcp_tools import _convert_mcp_tool_to_langchain
        agw_client = AsyncMock()
        with pytest.raises(ValueError, match="None"):
            _convert_mcp_tool_to_langchain(None, agw_client)

    def test_tool_description_enhanced(self):
        from mcp_tools import _convert_mcp_tool_to_langchain
        agw_client = AsyncMock()
        mcp_tool = self._make_mcp_tool(description="Retrieve sales orders")
        result = _convert_mcp_tool_to_langchain(mcp_tool, agw_client)
        assert "Retrieve sales orders" in result.description

    def test_tool_with_required_and_optional_fields(self):
        from mcp_tools import _convert_mcp_tool_to_langchain
        agw_client = AsyncMock()
        props = {
            "customer_id": {"type": "string", "description": "Customer ID"},
            "sales_org": {"type": "string", "description": "Sales org"},
            "quantity": {"type": "integer", "description": "Qty"},
            "discount_pct": {"type": "number", "description": "Discount %"},
        }
        mcp_tool = self._make_mcp_tool(
            props=props,
            required=["customer_id"]
        )
        result = _convert_mcp_tool_to_langchain(mcp_tool, agw_client)
        assert result.args_schema is not None
