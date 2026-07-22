# -*- coding: utf-8 -*-
"""Tests for MCP defaults in the agent service example."""
import ast
import os
from pathlib import Path
from typing import Any
from unittest import main, TestCase
from unittest.mock import patch


_MAIN_PATH = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "agent_service"
    / "main.py"
)


def _load_luckin_block() -> ast.Module:
    tree = ast.parse(_MAIN_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.If) and any(
            isinstance(child, ast.Constant)
            and child.value == "LUCKIN_MCP_TOKEN"
            for child in ast.walk(node.test)
        ):
            return ast.fix_missing_locations(
                ast.Module(body=[node], type_ignores=[]),
            )
    raise AssertionError("Luckin MCP configuration block was not found")


def _execute_luckin_block(
    token: str | None,
) -> list[dict[str, Any]]:
    default_mcps: list[dict[str, Any]] = []
    namespace = {
        "os": os,
        "default_mcps": default_mcps,
        "MCPClient": lambda **kwargs: kwargs,
        "HttpMCPConfig": lambda **kwargs: kwargs,
    }
    environment = {} if token is None else {"LUCKIN_MCP_TOKEN": token}
    with patch.dict(os.environ, environment, clear=True):
        exec(
            compile(_load_luckin_block(), str(_MAIN_PATH), "exec"),
            namespace,
        )
    return default_mcps


class AgentServiceMainTest(TestCase):
    """Test optional MCP registration in the example service."""

    def test_luckin_mcp_uses_environment_token(self) -> None:
        clients = _execute_luckin_block("test-luckin-token")

        self.assertEqual(
            clients,
            [
                {
                    "name": "my-coffee",
                    "mcp_config": {
                        "url": (
                            "https://gwmcp.lkcoffee.com/order/user/mcp"
                        ),
                        "headers": {
                            "Authorization": "Bearer test-luckin-token",
                        },
                    },
                    "is_stateful": False,
                },
            ],
        )

    def test_luckin_mcp_is_omitted_without_token(self) -> None:
        clients = _execute_luckin_block(None)

        self.assertEqual(clients, [])


if __name__ == "__main__":
    main()
