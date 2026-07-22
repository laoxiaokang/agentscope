# -*- coding: utf-8 -*-
"""Tests for the agent service's Zilliz Cloud configuration."""
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


def _load_milvus_builder() -> ast.Module:
    tree = ast.parse(_MAIN_PATH.read_text(encoding="utf-8"))
    selected: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            names = {
                child.id
                for child in ast.walk(node)
                if isinstance(child, ast.Name)
            }
            if "_DEFAULT_MILVUS_URI" in names:
                selected.append(node)
        elif (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_build_vector_store"
        ):
            selected.append(node)

    if len(selected) != 2:
        raise AssertionError("Milvus environment configuration was not found")
    return ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))


def _build_store(environment: dict[str, str]) -> dict[str, Any]:
    namespace = {
        "os": os,
        "MilvusLiteStore": lambda **kwargs: kwargs,
    }
    with patch.dict(os.environ, environment, clear=True):
        exec(compile(_load_milvus_builder(), str(_MAIN_PATH), "exec"), namespace)
        return namespace["_build_vector_store"]()


class AgentServiceMilvusConfigTest(TestCase):
    """Verify safe Zilliz Cloud configuration in the example service."""

    def test_uses_environment_token_and_connection_overrides(self) -> None:
        store = _build_store(
            {
                "MILVUS_URI": " https://milvus.example.test ",
                "MILVUS_TOKEN": "test-milvus-token",
                "MILVUS_DB_NAME": "knowledge",
            },
        )

        self.assertEqual(
            store,
            {
                "uri": "https://milvus.example.test",
                "metric_type": "COSINE",
                "client_kwargs": {
                    "token": "test-milvus-token",
                    "db_name": "knowledge",
                },
            },
        )

    def test_uses_the_project_cluster_endpoint_by_default(self) -> None:
        store = _build_store({"MILVUS_TOKEN": "test-milvus-token"})

        self.assertEqual(
            store["uri"],
            "https://in03-27c7c2ecead182f.serverless.ali-cn-hangzhou."
            "cloud.zilliz.com.cn",
        )

    def test_rejects_a_missing_token(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "MILVUS_TOKEN"):
            _build_store({})


if __name__ == "__main__":
    main()
