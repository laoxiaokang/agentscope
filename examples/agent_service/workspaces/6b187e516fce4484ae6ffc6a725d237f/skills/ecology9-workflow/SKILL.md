---
name: ecology9-workflow
description: Fast, read-only and controlled WorkflowService operations for Weaver E-cology 9. Use when Codex needs to query an authorized employee's pending, started, handled, processed, creatable, or summary workflows, or explicitly approve, reject, or forward reviewed pending workflows and summarize their outcomes without using a browser.
---

# Ecology 9 Workflow Operations

Use the bundled WorkflowService clients for authorized OA workflow queries and controlled approval actions. This skill is intentionally separate from Token SSO configuration; do not load SSO references for workflow tasks.

## One-Step Query Fast Path

When the user supplies the latest workcode, refers to that employee as "my/me", and clearly asks for one of the modes below, run `scripts/ecology_workflow_query.py` immediately. Do not first inspect `config.local.json`, read references, run `--help`, inspect script source, fetch WSDL, or perform other preflight calls; the script validates its configuration and inputs.

- Map pending/todo/waiting for me to `todo`; started by me to `started`; handled by me to `handled`; archived/fully processed to `processed`; templates I can start to `creatable`; several counts to `summary`.
- Add `--include-items` when the user asks to view tasks, titles, or details. Omit it when only a count is requested.
- Run exactly one query command, then summarize its sanitized JSON. Do not repeat a successful query.

```bash
python scripts/ecology_workflow_query.py --workcode {WORKCODE} --mode todo --include-items
```

## Local Runtime Configuration

The query and action scripts read `config.local.json` themselves. Inspect it only after a missing/invalid-configuration error or before asking the user for the OA base URL. When inspected:

- Read `oaBaseUrl` as the default OA base URL.
- Require an absolute `http` or `https` URL with no query string or fragment.
- Keep the resolved host in a runtime variable and never repeat it in user-visible commands, examples, logs, screenshots, or final responses.
- Treat `config.local.json` as local sensitive configuration and never copy it into source control or generated artifacts.

## Fast Read-Only Queries

Use the one-step fast path for routine queries. Read [references/workflow-query.md](references/workflow-query.md) only for ambiguous mode selection, unusual pagination requirements, or query troubleshooting. The canonical client is the standard-library-only `scripts/ecology_workflow_query.py`; use `scripts/ecology_workflow_query.ps1` only when a PowerShell-compatible entrypoint is required.

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
- After every executed action, return the post-action receipt defined in `references/workflow-action.md`. Include sanitized key form data, the reviewed action and opinion, the verified result, and aggregate counts when several items were processed; never respond with only a generic success sentence.

## Guardrails

- Never expose internal hosts, identifiers, application credentials, tokens, raw SOAP, or workflow request IDs in user-visible output.
- Never create, delete, force-over, or write opinions outside the controlled action script with separate authorization and a reviewed payload.
- Prefer HTTPS. If the configured deployment uses HTTP, keep the call inside a trusted network or protected proxy.
- Use one-time SSO tokens only through the separate `ecology9-sso` skill; do not request tokens from browser JavaScript.

## Output Contract

For queries, return the mode, count, query time, elapsed time, and requested sanitized details. State when results are truncated.

For actions, return a concise single-item or batch receipt with the sanitized title, key form fields, node, reviewed action and opinion, three-state outcome, verification result, and optional elapsed time. Do not expose the OA host, workcode, internal user ID, internal request ID, raw SOAP, action button names, or internal template IDs.
