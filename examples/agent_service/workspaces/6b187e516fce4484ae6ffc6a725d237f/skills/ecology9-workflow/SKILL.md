---
name: ecology9-workflow
description: Fast, read-only and controlled WorkflowService operations for Weaver E-cology 9. Use when Codex needs to query an authorized employee's pending, started, handled, processed, creatable, or summary workflows, or explicitly approve, reject, or forward one reviewed pending workflow without using a browser.
---

# Ecology 9 Workflow Operations

Use the bundled WorkflowService clients for authorized OA workflow queries and controlled approval actions. This skill is intentionally separate from Token SSO configuration; do not load SSO references for workflow tasks.

## Local Runtime Configuration

Before asking for the OA base URL, check `config.local.json` in this skill directory. When present:

- Read `oaBaseUrl` as the default OA base URL.
- Require an absolute `http` or `https` URL with no query string or fragment.
- Keep the resolved host in a runtime variable and never repeat it in user-visible commands, examples, logs, screenshots, or final responses.
- Treat `config.local.json` as local sensitive configuration and never copy it into source control or generated artifacts.

## Fast Read-Only Queries

Read [references/workflow-query.md](references/workflow-query.md), then run the canonical standard-library-only `scripts/ecology_workflow_query.py`. Use `scripts/ecology_workflow_query.ps1` only when a PowerShell-compatible entrypoint is required; it is a thin wrapper around the Python implementation.

- Omit item inclusion when only a count is requested.
- Add item inclusion when titles or details are requested.
- Use `summary` for several counts so the employee is resolved once.
- Use the latest explicitly supplied workcode for "my" queries. Treat a workcode as an identifier, not authentication.
- Require explicit authorization before querying another employee.
- Do not fetch the WSDL or handcraft SOAP during normal queries.
- Summarize the script JSON without exposing the host, workcode, internal user ID, request ID, raw SOAP, or SSO data.

## Controlled Approval Actions

For an explicitly authorized approval or rejection, read [references/workflow-action.md](references/workflow-action.md), then run `scripts/ecology_workflow_action.py`.

- Select exactly one pending item by expected title or a request ID obtained in the current authorized runtime.
- Require an explicit `approve`, `reject`, or `forward` action. Approval and rejection require a non-empty opinion; forwarding may use an empty opinion when the OA contract allows it.
- For forwarding, require the recipient's workcode and resolve it once to the OA internal user ID. Pass one recipient ID as the documented `forwardoperator` string and leave `clientip` empty unless explicitly configured.
- Run without `--confirm` for a sanitized preview when any reviewed detail is missing.
- Add `--confirm` only after explicit authorization of the reviewed target, action, and opinion.
- The script validates the current title, node, action button, and required editable fields before approval/rejection; forwarding validates the current title, node, and `forwardButtonName`.
- Approval/rejection use `submitWorkflowRequest`; forwarding uses `forwardWorkflowRequest` with the documented five parameters. Each write is attempted exactly once. Approval/rejection verify that the operator's item left the pending list; forwarding verifies that the recipient received the matching pending item, because this deployment may retain the operator's original todo.
- Trust only `outcome: confirmed`. Treat `not_applied` as an explicit failure and `unknown` as inconclusive; never retry either automatically.

## Guardrails

- Never expose internal hosts, identifiers, application credentials, tokens, raw SOAP, or workflow request IDs in user-visible output.
- Never create, delete, force-over, or write opinions outside the controlled action script with separate authorization and a reviewed payload.
- Prefer HTTPS. If the configured deployment uses HTTP, keep the call inside a trusted network or protected proxy.
- Use one-time SSO tokens only through the separate `ecology9-sso` skill; do not request tokens from browser JavaScript.

## Output Contract

For queries, return the mode, count, query time, elapsed time, and requested sanitized details. State when results are truncated.

For actions, return the sanitized target title and node, action, three-state outcome, verification result, and elapsed time. Do not expose the OA host, workcode, internal user ID, internal request ID, raw SOAP, or internal template IDs.
