"""Tests for agent file structure and module validity."""

import pytest


@pytest.mark.structure
class TestRequiredFiles:
    """Test that all required files exist."""

    def test_agent_directory_exists(self, agent_path):
        """Test that the generated_agent directory exists."""
        assert agent_path.exists(), f"Agent directory not found: {agent_path}"
        assert agent_path.is_dir(), f"Agent path is not a directory: {agent_path}"

    def test_app_directory_exists(self, agent_app_path):
        """Test that the app directory exists."""
        assert agent_app_path.exists(), f"App directory not found: {agent_app_path}"
        assert agent_app_path.is_dir(), f"App path is not a directory: {agent_app_path}"

    def test_requirements_txt_exists(self, agent_path):
        """Test that requirements.txt exists."""
        req_file = agent_path / "requirements.txt"
        assert req_file.exists(), "requirements.txt is missing"
        assert req_file.stat().st_size > 0, "requirements.txt is empty"

    def test_agent_py_exists(self, agent_app_path):
        """Test that app/agent.py exists."""
        f = agent_app_path / "agent.py"
        assert f.exists(), "app/agent.py is missing"

    def test_mcp_tools_py_exists(self, agent_app_path):
        """Test that app/mcp_tools.py exists."""
        f = agent_app_path / "mcp_tools.py"
        assert f.exists(), "app/mcp_tools.py is missing"

    def test_main_py_exists(self, agent_app_path):
        """Test that app/main.py exists."""
        f = agent_app_path / "main.py"
        assert f.exists(), "app/main.py is missing"

    def test_mcp_mock_json_exists(self, agent_path):
        """Test that mcp-mock.json exists."""
        f = agent_path / "mcp-mock.json"
        assert f.exists(), "mcp-mock.json is missing"

    def test_agent_py_compiles(self, agent_app_path):
        """Test that app/agent.py compiles without syntax errors."""
        import py_compile
        py_compile.compile(str(agent_app_path / "agent.py"), doraise=True)

    def test_mcp_tools_py_compiles(self, agent_app_path):
        """Test that app/mcp_tools.py compiles without syntax errors."""
        import py_compile
        py_compile.compile(str(agent_app_path / "mcp_tools.py"), doraise=True)
