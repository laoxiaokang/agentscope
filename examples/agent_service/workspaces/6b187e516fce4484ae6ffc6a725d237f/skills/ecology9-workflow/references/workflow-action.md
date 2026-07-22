# Ecology Workflow Action Routing

Use `scripts/ecology_workflow_action.py` for one explicitly authorized approval, rejection, or transfer. The script uses the standard library, the configured local OA endpoint, and the reusable query client. It does not perform WSDL discovery.

## Commands

Preview a unique pending workflow:

```bash
python scripts/ecology_workflow_action.py \
  --workcode {WORKCODE} \
  --action approve \
  --remark {REMARK} \
  --expected-title {TITLE}
```

After explicit confirmation, run the same reviewed payload once with `--confirm`:

```bash
python scripts/ecology_workflow_action.py \
  --workcode {WORKCODE} \
  --action approve \
  --remark {REMARK} \
  --expected-title {TITLE} \
  --confirm
```

Use `--action reject` for rejection. Prefer `--expected-title`; use `--request-id` only when the internal ID came from the current authorized query and keep it out of user-visible output. Add `--expected-node` when the user reviewed a specific node.

Transfer a pending item to one recipient:

```bash
python scripts/ecology_workflow_action.py \
  --workcode {OPERATOR_WORKCODE} \
  --action forward \
  --recipient-workcode {RECIPIENT_WORKCODE} \
  --expected-title {TITLE} \
  --expected-node {NODE} \
  --confirm
```

Add `--remark {REMARK}` when a transfer opinion is needed. The documented `forwardWorkflowRequest` contract maps `in0=requestId`, `in1=forwardoperator` (a comma-separated recipient-ID string), `in2=remark`, `in3=userId`, and `in4=clientip`; the script sends an empty client IP unless explicitly supplied.

## Fixed Action Flow

1. Load and validate `oaBaseUrl` from `config.local.json`.
2. Resolve the employee once and reuse one HTTP connection.
3. Fetch the pending count and list, then require exactly one selector match.
4. Call `getWorkflowRequest` and validate the request title, current node, available action button, and required editable fields.
5. Return a sanitized preview unless `--confirm` is present.
6. For approval/rejection, copy the complete returned `WorkflowRequestInfo`, set its embedded opinion and the submit opinion argument, then call `submitWorkflowRequest` exactly once. For transfer, resolve the recipient and call `forwardWorkflowRequest` once with the documented scalar parameters.
7. Whether the write response succeeds, fails, or is lost, re-query pending workflows without repeating the write. For transfer, confirm the recipient received the matching todo; do not assume the operator's todo disappears.
8. Return exactly one mutation outcome: `confirmed`, `not_applied`, or `unknown`.

Read-only calls retry once on transport failures. `submitWorkflowRequest` never retries.

## Mutation Outcomes

| Outcome | Meaning | Exit code |
|---|---|---|
| `confirmed` | Approval/rejection left the operator's pending list, or forwarding created the recipient's matching todo, including when the write response was lost. | `0` |
| `not_applied` | OA explicitly did not accept the action and the target remains pending. | `2` |
| `unknown` | The response or read-only verification is inconclusive. | `3` |

Trust only `confirmed` as completion. Never automatically repeat `not_applied` or `unknown`; run a fresh pending query and obtain explicit authorization before another write.

## Authorization and Output

Treat a workcode as an identifier, not authentication. Require explicit authorization for the operator, target workflow, action, recipient when forwarding, and opinion when used. A direct instruction containing the required fields is sufficient; otherwise stop after preview and ask for the missing confirmation.

The script returns JSON without the endpoint, workcode, internal user ID, internal request ID, or raw SOAP. Summarize only the target title and node, mutation outcome, verification result, and elapsed time.
