"""Unit tests for cost-center-intelligence-agent mcp_tools.py."""
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
        assert len(tools) == 2

    def test_tool_names(self):
        from mcp_tools import _build_mock_tools
        tools = _build_mock_tools()
        names = {t.name for t in tools}
        assert "count_cost_centers" in names
        assert "list_top_cost_centers" in names

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

    def test_count_tool_is_coroutine(self):
        from mcp_tools import _build_mock_tools
        tools = _build_mock_tools()
        count_tool = next(t for t in tools if t.name == "count_cost_centers")
        assert count_tool.coroutine is not None

    @pytest.mark.asyncio
    async def test_count_tool_returns_mock_data(self):
        from mcp_tools import _build_mock_tools
        tools = _build_mock_tools()
        count_tool = next(t for t in tools if t.name == "count_cost_centers")
        result = await count_tool.coroutine()
        data = json.loads(result)
        assert data["total_count"] == 142

    @pytest.mark.asyncio
    async def test_list_top_tool_returns_mock_data(self):
        from mcp_tools import _build_mock_tools
        tools = _build_mock_tools()
        list_tool = next(t for t in tools if t.name == "list_top_cost_centers")
        result = await list_tool.coroutine()
        data = json.loads(result)
        assert len(data["cost_centers"]) == 5

    def test_missing_mock_file_returns_empty(self, tmp_path, monkeypatch):
        import mcp_tools
        original = mcp_tools._MOCK_FILE
        mcp_tools._MOCK_FILE = tmp_path / "nonexistent.json"
        try:
            result = mcp_tools._build_mock_tools()
            assert result == []
        finally:
            mcp_tools._MOCK_FILE = original

    def test_invalid_json_returns_empty(self, tmp_path, monkeypatch):
        import mcp_tools
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("this is not json {{{{")
        original = mcp_tools._MOCK_FILE
        mcp_tools._MOCK_FILE = bad_file
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
    async def test_token_ignored_in_test_mode(self):
        from mcp_tools import get_mcp_tools
        tools = await get_mcp_tools("any-token-value")
        assert len(tools) > 0

    @pytest.mark.asyncio
    async def test_returns_both_tools_in_test_mode(self):
        from mcp_tools import get_mcp_tools
        tools = await get_mcp_tools(None)
        names = {t.name for t in tools}
        assert "count_cost_centers" in names
        assert "list_top_cost_centers" in names


class TestUserTokenContext:
    def test_set_and_get_user_token(self):
        from mcp_tools import set_user_token, get_user_token
        token_handle = set_user_token("test-token-abc")
        assert get_user_token() == "test-token-abc"

    def test_set_none_token(self):
        from mcp_tools import set_user_token, get_user_token
        set_user_token(None)
        assert get_user_token() is None

    def test_set_token_returns_token_object(self):
        from mcp_tools import set_user_token
        result = set_user_token("some-token")
        assert result is not None


class TestConvertMcpToolToLangchain:
    def _make_mcp_tool(self, name="test_tool", description="A test tool", props=None, required=None):
        tool = MagicMock()
        tool.name = name
        tool.description = description
        tool.server_name = "test:server:name"
        tool.fragment_name = "test-server"
        tool.input_schema = {
            "properties": props or {},
            "required": required or [],
        }
        return tool

    def test_returns_structured_tool(self):
        from mcp_tools import _convert_mcp_tool_to_langchain
        agw_client = AsyncMock()
        mcp_tool = self._make_mcp_tool()
        result = _convert_mcp_tool_to_langchain(mcp_tool, agw_client)
        from langchain_core.tools import StructuredTool
        assert isinstance(result, StructuredTool)

    def test_raises_on_none_tool(self):
        from mcp_tools import _convert_mcp_tool_to_langchain
        agw_client = AsyncMock()
        with pytest.raises(ValueError, match="None"):
            _convert_mcp_tool_to_langchain(None, agw_client)

    def test_tool_description_enhanced(self):
        from mcp_tools import _convert_mcp_tool_to_langchain
        agw_client = AsyncMock()
        mcp_tool = self._make_mcp_tool(description="Count them")
        result = _convert_mcp_tool_to_langchain(mcp_tool, agw_client)
        assert "Count them" in result.description

    def test_tool_with_typed_properties(self):
        from mcp_tools import _convert_mcp_tool_to_langchain
        agw_client = AsyncMock()
        props = {
            "top_n": {"type": "integer", "description": "Number"},
            "area": {"type": "string", "description": "Area"},
            "rate": {"type": "number", "description": "Rate"},
            "active": {"type": "boolean", "description": "Flag"},
        }
        mcp_tool = self._make_mcp_tool(props=props, required=["top_n"])
        result = _convert_mcp_tool_to_langchain(mcp_tool, agw_client)
        assert result.args_schema is not None
