# -*- coding: utf-8 -*-
"""Tests for MCP defaults in the agent service example."""
import ast
from collections.abc import Callable
import json
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
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


def _load_mcp_migration() -> Callable[
    [Path, str, list[str], dict[str, dict[str, object]]],
    int,
]:
    tree = ast.parse(_MAIN_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_migrate_persisted_mcp_configs"
        ):
            namespace = {
                "json": json,
                "os": os,
                "Path": Path,
                "_LOGGER": logging.getLogger(__name__),
            }
            module = ast.fix_missing_locations(
                ast.Module(body=[node], type_ignores=[]),
            )
            exec(compile(module, str(_MAIN_PATH), "exec"), namespace)
            return namespace["_migrate_persisted_mcp_configs"]
    raise AssertionError("MCP migration function was not found")


def _load_health_access_log_filter() -> Callable[[logging.LogRecord], bool]:
    tree = ast.parse(_MAIN_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.ClassDef)
            and node.name == "_HealthAccessLogFilter"
        ):
            namespace = {"logging": logging}
            module = ast.fix_missing_locations(
                ast.Module(body=[node], type_ignores=[]),
            )
            exec(compile(module, str(_MAIN_PATH), "exec"), namespace)
            return namespace["_HealthAccessLogFilter"]().filter
    raise AssertionError("Health access log filter was not found")


class AgentServiceMainTest(TestCase):
    """Test optional MCP registration in the example service."""

    def test_redis_message_bus_reuses_storage_connection_settings(
        self,
    ) -> None:
        tree = ast.parse(_MAIN_PATH.read_text(encoding="utf-8"))
        constructor_kwargs: dict[str, dict[str, str]] = {}

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func,
                ast.Name,
            ):
                continue
            if node.func.id not in {"RedisStorage", "RedisMessageBus"}:
                continue
            constructor_kwargs[node.func.id] = {
                keyword.arg: ast.dump(keyword.value)
                for keyword in node.keywords
                if keyword.arg is not None
            }

        self.assertEqual(
            constructor_kwargs["RedisStorage"],
            constructor_kwargs["RedisMessageBus"],
        )
        self.assertEqual(
            set(constructor_kwargs["RedisMessageBus"]),
            {"host", "port", "password", "db"},
        )

        create_app_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "create_app"
        ]
        self.assertEqual(len(create_app_calls), 1)
        message_bus_arg = next(
            keyword.value
            for keyword in create_app_calls[0].keywords
            if keyword.arg == "message_bus"
        )
        self.assertIsInstance(message_bus_arg, ast.Name)
        self.assertEqual(message_bus_arg.id, "message_bus")

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

    def test_migrates_legacy_persisted_mcp_settings(self) -> None:
        migrate = _load_mcp_migration()
        specs = [
            {
                "name": "browser-use",
                "is_stateful": True,
                "mcp_config": {
                    "type": "stdio_mcp",
                    "command": "npx",
                    "args": ["@playwright/mcp@latest"],
                },
            },
            {
                "name": "amap",
                "is_stateful": True,
                "mcp_config": {
                    "type": "http_mcp",
                    "url": "https://mcp.amap.com/mcp?key=test",
                },
            },
            {
                "name": "custom-http",
                "is_stateful": True,
                "mcp_config": {
                    "type": "http_mcp",
                    "url": "https://example.test/mcp",
                },
            },
        ]

        with TemporaryDirectory() as temporary_dir:
            workspace = Path(temporary_dir) / "agent-id"
            workspace.mkdir()
            mcp_file = workspace / ".mcp"
            mcp_file.write_text(json.dumps(specs), encoding="utf-8")
            second_workspace = Path(temporary_dir) / "second-agent-id"
            second_workspace.mkdir()
            second_mcp_file = second_workspace / ".mcp"
            second_mcp_file.write_text(
                json.dumps(
                    [
                        {
                            "name": "browser-use",
                            "is_stateful": True,
                            "mcp_config": {
                                "type": "stdio_mcp",
                                "command": "playwright-mcp",
                                "args": ["--headless", "--no-sandbox"],
                            },
                        },
                    ],
                ),
                encoding="utf-8",
            )

            migrated = migrate(
                Path(temporary_dir),
                "playwright-mcp",
                ["--headless"],
                {
                    "amap": {
                        "name": "amap",
                        "is_stateful": False,
                        "mcp_config": {
                            "type": "http_mcp",
                            "url": "https://mcp.amap.com/mcp?key=current",
                        },
                    },
                    "my-coffee": {
                        "name": "my-coffee",
                        "is_stateful": False,
                        "mcp_config": {
                            "type": "http_mcp",
                            "url": "https://coffee.example.test/mcp",
                            "headers": {"Authorization": "Bearer current"},
                        },
                    },
                },
            )
            result = json.loads(mcp_file.read_text(encoding="utf-8"))
            second_result = json.loads(
                second_mcp_file.read_text(encoding="utf-8"),
            )

        self.assertEqual(migrated, 2)
        self.assertEqual(
            result[0]["mcp_config"],
            {
                "type": "stdio_mcp",
                "command": "playwright-mcp",
                "args": ["--headless"],
            },
        )
        self.assertFalse(result[1]["is_stateful"])
        self.assertEqual(
            result[1]["mcp_config"]["url"],
            "https://mcp.amap.com/mcp?key=current",
        )
        self.assertTrue(result[2]["is_stateful"])
        self.assertEqual(result[3]["name"], "my-coffee")
        self.assertFalse(result[3]["is_stateful"])
        self.assertEqual(
            second_result[0]["mcp_config"]["args"],
            ["--headless"],
        )

    def test_health_access_log_filter_keeps_failures_and_other_requests(
        self,
    ) -> None:
        filter_log = _load_health_access_log_filter()

        def record(
            method: str,
            path: str,
            status_code: int,
        ) -> logging.LogRecord:
            return logging.LogRecord(
                name="uvicorn.access",
                level=logging.INFO,
                pathname=__file__,
                lineno=1,
                msg='%s - "%s %s HTTP/%s" %s',
                args=("127.0.0.1:1234", method, path, "1.1", status_code),
                exc_info=None,
            )

        self.assertFalse(filter_log(record("GET", "/health", 200)))
        self.assertFalse(filter_log(record("GET", "/health?probe=1", 204)))
        self.assertTrue(filter_log(record("GET", "/health", 500)))
        self.assertTrue(filter_log(record("POST", "/health", 200)))
        self.assertTrue(filter_log(record("GET", "/api/health", 200)))


if __name__ == "__main__":
    main()
