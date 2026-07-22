# Luckin Coffee MCP Configuration Design

## Goal

Register the Luckin Coffee Streamable HTTP MCP server in the agent service
without storing its bearer token in source control.

## Configuration

- Server name: `my-coffee`
- Endpoint: `https://gwmcp.lkcoffee.com/order/user/mcp`
- Authentication: an `Authorization` header containing the bearer token
- Token source: the `LUCKIN_MCP_TOKEN` environment variable
- Registration behavior: append the server to `default_mcps` only when the
  environment variable is present

This follows the existing conditional `AMAP_API_KEY` configuration in
`examples/agent_service/main.py`. A missing Luckin token will not prevent the
agent service from starting.

## Runtime Behavior

The MCP client uses `HttpMCPConfig` and is named `my-coffee`, matching the
server name expected by the Luckin integration. It is configured as
non-stateful because the remote Streamable HTTP endpoint can establish its
own temporary request session for each operation. This also avoids holding a
persistent connection for a remote service that is used only on demand.

`default_mcps` applies only when a workspace is first initialized. Existing
workspace `.mcp` files remain authoritative and will not be modified by this
change. An existing agent must add `my-coffee` through its MCP configuration
or be initialized with a new workspace.

## Security And Errors

The token is never written to the repository or logs. Users set it in the
process environment before starting `python main.py`. Invalid or expired
tokens are reported by the remote MCP service when the client connects.

## Verification

Verification will cover Python syntax, construction with a dummy environment
token, formatting checks, and a scan confirming no real Luckin token was
added to tracked files.
