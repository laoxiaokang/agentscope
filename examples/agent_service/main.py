# -*- coding: utf-8 -*-
"""The example script to start the agent service."""
import json
import logging
import os
import shlex
from pathlib import Path

import uvicorn
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware

from agentscope.app import create_app, SubAgentTemplate
from agentscope.app.message_bus import RedisMessageBus
from agentscope.app.rag.blob_store import S3BlobStore
from agentscope.app.rag.knowledge_base_manager import CollectionPerKbManager
from agentscope.app.storage import RedisStorage
from agentscope.app.workspace_manager import LocalWorkspaceManager
from agentscope.mcp import MCPClient, StdioMCPConfig, HttpMCPConfig
from agentscope.permission import PermissionContext, PermissionMode
from agentscope.rag import MilvusLiteStore


_DEFAULT_MILVUS_URI = (
    "https://in03-27c7c2ecead182f.serverless.ali-cn-hangzhou."
    "cloud.zilliz.com.cn"
)
_LOGGER = logging.getLogger(__name__)
_WORKSPACES_DIR = Path(__file__).resolve().parent / "workspaces"


class _HealthAccessLogFilter(logging.Filter):
    """Suppress successful access logs emitted by the container probe."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if not isinstance(args, tuple) or len(args) != 5:
            return True

        _, method, full_path, _, status_code = args
        try:
            status_code = int(status_code)
        except (TypeError, ValueError):
            return True

        path = str(full_path).split("?", 1)[0]
        return not (
            method == "GET"
            and path == "/health"
            and status_code < 400
        )


logging.getLogger("uvicorn.access").addFilter(_HealthAccessLogFilter())


def _build_vector_store() -> MilvusLiteStore:
    """Build the persistent Zilliz Cloud store from the environment."""
    token = os.getenv("MILVUS_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "MILVUS_TOKEN is required to connect to the configured Milvus "
            "endpoint. Set it before starting the agent service.",
        )

    uri = os.getenv("MILVUS_URI", _DEFAULT_MILVUS_URI).strip()
    if not uri:
        raise RuntimeError("MILVUS_URI must not be empty.")

    return MilvusLiteStore(
        uri=uri,
        metric_type="COSINE",
        client_kwargs={
            "token": token,
            "db_name": os.getenv("MILVUS_DB_NAME", "default").strip()
            or "default",
        },
    )


def _optional_env(name: str) -> str | None:
    """Return a stripped environment value, or ``None`` when empty."""
    value = os.getenv(name, "").strip()
    return value or None


def _env_bool(name: str, default: bool) -> bool:
    """Parse a boolean environment variable with validation."""
    value = _optional_env(name)
    if value is None:
        return default
    normalized = value.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(
        f"{name} must be one of true/false, yes/no, on/off, or 1/0.",
    )


def _build_blob_store() -> S3BlobStore:
    """Build the S3-compatible blob store from the environment."""
    bucket = _optional_env("S3_BUCKET")
    if bucket is None:
        raise RuntimeError("S3_BUCKET is required for document storage.")

    from aiobotocore.config import AioConfig

    config = AioConfig(
        signature_version=os.getenv("S3_SIGNATURE_VERSION", "s3v4").strip()
        or "s3v4",
        s3={
            "addressing_style": os.getenv(
                "S3_ADDRESSING_STYLE",
                "auto",
            ).strip()
            or "auto",
        },
    )
    return S3BlobStore(
        bucket=bucket,
        region_name=_optional_env("AWS_REGION")
        or _optional_env("AWS_DEFAULT_REGION"),
        endpoint_url=_optional_env("S3_ENDPOINT"),
        aws_access_key_id=_optional_env("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=_optional_env("AWS_SECRET_ACCESS_KEY"),
        session_token=_optional_env("AWS_SESSION_TOKEN"),
        use_ssl=_env_bool("S3_USE_SSL", True),
        config=config,
    )


def _migrate_persisted_mcp_configs(
    workspaces_dir: Path,
    browser_command: str,
    browser_args: list[str],
    managed_http_specs: dict[str, dict[str, object]],
) -> int:
    """Upgrade service-managed MCP settings saved by older deployments."""
    migrated_files = 0
    for mcp_file in workspaces_dir.glob("*/.mcp"):
        try:
            specs = json.loads(mcp_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            _LOGGER.warning("Unable to migrate %s: %s", mcp_file, error)
            continue

        if not isinstance(specs, list):
            _LOGGER.warning("Unable to migrate %s: expected a JSON list", mcp_file)
            continue

        changed = False
        migrated_specs = []
        configured_http_names: set[str] = set()
        for spec in specs:
            if not isinstance(spec, dict):
                migrated_specs.append(spec)
                continue
            config = spec.get("mcp_config")
            if not isinstance(config, dict):
                migrated_specs.append(spec)
                continue

            name = spec.get("name")
            if name in {"amap", "my-coffee"}:
                configured_spec = managed_http_specs.get(name)
                if configured_spec is None:
                    changed = True
                    continue
                configured_http_names.add(name)
                configured_config = configured_spec["mcp_config"]
                if (
                    config != configured_config
                    or spec.get("is_stateful") is not False
                ):
                    spec["mcp_config"] = configured_config
                    spec["is_stateful"] = False
                    changed = True

            legacy_browser_args = config.get("args") or []
            is_legacy_npx_browser = (
                config.get("command") == "npx"
                and any(
                    isinstance(arg, str)
                    and arg.startswith("@playwright/mcp@")
                    for arg in legacy_browser_args
                )
            )
            is_unconfigured_image_browser = (
                config.get("command") == browser_command
                and legacy_browser_args
                in (
                    [],
                    ["--headless", "--no-sandbox"],
                )
                and bool(browser_args)
            )
            if (
                name == "browser-use"
                and config.get("type") == "stdio_mcp"
                and (is_legacy_npx_browser or is_unconfigured_image_browser)
                and (
                    config.get("command") != browser_command
                    or legacy_browser_args != browser_args
                )
            ):
                config["command"] = browser_command
                config["args"] = browser_args
                changed = True

            migrated_specs.append(spec)

        for name, configured_spec in managed_http_specs.items():
            if name not in configured_http_names:
                migrated_specs.append(configured_spec)
                changed = True

        if changed:
            temporary_file = mcp_file.with_name(f"{mcp_file.name}.tmp")
            try:
                temporary_file.write_text(
                    json.dumps(migrated_specs, ensure_ascii=False, indent=2)
                    + "\n",
                    encoding="utf-8",
                )
                os.replace(temporary_file, mcp_file)
            except OSError as error:
                temporary_file.unlink(missing_ok=True)
                _LOGGER.warning("Unable to migrate %s: %s", mcp_file, error)
                continue
            migrated_files += 1

    return migrated_files


_PLAYWRIGHT_MCP_COMMAND = os.getenv("PLAYWRIGHT_MCP_COMMAND", "npx")
_PLAYWRIGHT_MCP_ARGS = shlex.split(
    os.getenv("PLAYWRIGHT_MCP_ARGS", "@playwright/mcp@latest"),
)

default_mcps = [
    MCPClient(
        name="browser-use",
        mcp_config=StdioMCPConfig(
            command=_PLAYWRIGHT_MCP_COMMAND,
            args=_PLAYWRIGHT_MCP_ARGS,
        ),
        is_stateful=True,
    ),
]

if os.getenv("AMAP_API_KEY"):
    default_mcps.append(
        MCPClient(
            name="amap",
            mcp_config=HttpMCPConfig(
                url=f"https://mcp.amap.com/mcp?key="
                f"{os.environ['AMAP_API_KEY']}",
            ),
            is_stateful=False,
        ),
    )

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

_migrated_mcp_files = _migrate_persisted_mcp_configs(
    _WORKSPACES_DIR,
    _PLAYWRIGHT_MCP_COMMAND,
    _PLAYWRIGHT_MCP_ARGS,
    {
        client.name: client.model_dump(mode="json")
        for client in default_mcps
        if client.name in {"amap", "my-coffee"}
    },
)
if _migrated_mcp_files:
    _LOGGER.info(
        "Migrated persisted MCP settings in %d workspace(s)",
        _migrated_mcp_files,
    )

_REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
_REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
_REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None
_REDIS_DB = int(os.getenv("REDIS_DB", "0"))

storage = RedisStorage(
    host=_REDIS_HOST,
    port=_REDIS_PORT,
    password=_REDIS_PASSWORD,
    db=_REDIS_DB,
)
message_bus = RedisMessageBus(
    host=_REDIS_HOST,
    port=_REDIS_PORT,
    password=_REDIS_PASSWORD,
    db=_REDIS_DB,
)

vector_store = _build_vector_store()
blob_store = _build_blob_store()

app = create_app(
    storage=storage,
    blob_store=blob_store,
    message_bus=message_bus,
    workspace_manager=LocalWorkspaceManager(
        basedir=str(_WORKSPACES_DIR),
        # The default MCP servers that will be added into the workspace
        default_mcps=default_mcps,
    ),
    # Each knowledge base gets its own collection in the configured Milvus
    # store, so different embedding dimensions can coexist.
    knowledge_base_manager=CollectionPerKbManager(
        storage=storage,
        vector_store=vector_store,
    ),
    # Customize your own subagent templates
    custom_subagent_templates=[
        SubAgentTemplate(
            type="explorer",
            description=(
                "Read-only agents specialized in exploration tasks. It can "
                "read files but cannot modify, create, or delete them. Use "
                "this agent type when you need to investigate the codebase, "
                "understand its structure, or gather information from files "
                "to support planning—without making any changes."
            ),
            system_prompt_template="""You are {member_name}, an explorer \
agent in team '{team_name}' led by {leader_name}.

Team purpose: {team_description}

Your role: {member_description}

## Responsibilities
- Complete the exploration tasks assigned by the team leader.
- You are read-only: you may inspect files and the codebase, but you must \
never modify, create, or delete anything.

## Reporting
- Always report the task result back to {leader_name} using the TeamSay \
tool, whether the task succeeds or fails.
- Keep your private reasoning private; only share conclusions and findings \
that the leader needs.

Note: `TeamSay` is your ONLY channel to communicate with {leader_name} and \
the other team members. Any other output you produce is invisible to them, \
so anything you want them to see MUST be sent through `TeamSay`.""",
            permission_context=PermissionContext(
                # Read-only
                mode=PermissionMode.BYPASS,
            ),
        ),
    ],
    extra_middlewares=[
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        ),
    ],
)


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    """Return a lightweight container health signal."""
    return {"status": "ok"}


if __name__ == "__main__":
    # Start the service
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("UVICORN_RELOAD", "").lower()
        in {"1", "true", "yes"},
    )
