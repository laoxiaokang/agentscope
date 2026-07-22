# Luckin Coffee MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an environment-authenticated Luckin Coffee MCP server to the agent service defaults.

**Architecture:** Extend the existing `default_mcps` construction in `examples/agent_service/main.py` with a conditional HTTP client. Read the bearer token only from `LUCKIN_MCP_TOKEN`, and omit the server when the variable is absent so existing startup behavior remains unchanged.

**Tech Stack:** Python, AgentScope `MCPClient`, `HttpMCPConfig`, `unittest`, Python `ast`

---

### Task 1: Specify Luckin MCP registration behavior

**Files:**
- Create: `tests/example_agent_service_main_test.py`
- Read: `examples/agent_service/main.py`

- [x] **Step 1: Add a test harness for the isolated configuration branch**

```python
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
```

- [x] **Step 2: Test registration with a configured token**

```python
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
```

- [x] **Step 3: Test omission when the token is absent**

```python
    def test_luckin_mcp_is_omitted_without_token(self) -> None:
        clients = _execute_luckin_block(None)

        self.assertEqual(clients, [])


if __name__ == "__main__":
    main()
```

- [x] **Step 4: Run the focused tests and verify the missing block fails**

Run: `python tests/example_agent_service_main_test.py`

Expected: both tests fail with `Luckin MCP configuration block was not found`.

### Task 2: Register the Luckin MCP server

**Files:**
- Modify: `examples/agent_service/main.py` after the AMAP MCP block
- Test: `tests/example_agent_service_main_test.py`

- [x] **Step 1: Add conditional MCP construction**

```python
if os.getenv("LUCKIN_MCP_TOKEN"):
    default_mcps.append(
        MCPClient(
            name="my-coffee",
            mcp_config=HttpMCPConfig(
                url="https://gwmcp.lkcoffee.com/order/user/mcp",
                headers={
                    "Authorization": (
                        f"Bearer {os.environ['LUCKIN_MCP_TOKEN']}"
                    ),
                },
            ),
            is_stateful=False,
        ),
    )
```

- [x] **Step 2: Run the focused tests and verify they pass**

Run: `python tests/example_agent_service_main_test.py`

Expected: `2 passed`.

- [x] **Step 3: Verify Python syntax**

Run: `python -m py_compile examples/agent_service/main.py tests/example_agent_service_main_test.py`

Expected: command exits successfully without output.

- [x] **Step 4: Check the diff and whitespace**

Run: `git diff --check -- examples/agent_service/main.py tests/example_agent_service_main_test.py`

Expected: command exits successfully without whitespace errors.

- [x] **Step 5: Confirm no Luckin bearer token was persisted**

Run: PowerShell `Select-String` over both files and reject any `Bearer ` line
other than the environment-variable expression and the fixed test token.

Expected: no matches.

No Git commit is created, per the user's instruction.
