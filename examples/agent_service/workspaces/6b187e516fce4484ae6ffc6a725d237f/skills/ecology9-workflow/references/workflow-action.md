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

The script returns JSON without the endpoint, workcode, internal user ID, internal request ID, or raw SOAP. It includes the reviewed opinion and up to eight non-empty, visible main-form fields in `keyFields`; secret-like and internal-ID fields are filtered. `keyFieldsTruncated` states whether more safe fields were available.

## Post-action Receipt

After all requested writes finish, always return a concise result receipt instead of only saying that processing succeeded.

- For one item, use a compact labeled list. For two or more items, use a Markdown table with `#`, `流程`, `关键数据`, `操作/意见`, and `结果` columns.
- Start with `已完成 N 个流程` only when all outcomes are `confirmed`. Otherwise state `N/M 个流程已确认`, followed by the number not applied or awaiting verification.
- Use the workflow title as `流程`. Render the most decision-relevant one to four entries from `keyFields` as `名称：值`; state `无可安全展示的关键字段` when the list is empty.
- Render the reviewed action and opinion together. Use `同意`, `退回`, or `转发` for the operation; do not invent an opinion or forwarding recipient that was not reviewed.
- Map `confirmed` to `已批准`, `已退回`, or `已转发`. Map `not_applied` to `未生效`; map `unknown` to `结果待核验`. Never describe `not_applied` or `unknown` as completed.
- Translate verification consistently: `left_todo` as `已离开我的待办`, `still_todo` as `仍在我的待办`, `recipient_todo_created` as `已送达接收人待办`, `operator_left_todo` as `已离开我的待办`, `recipient_not_found` as `未在接收人待办中找到`, `recipient_query_unavailable` as `接收人待办核验不可用`, `unavailable` as `待办核验不可用`, and `inconclusive` as `核验结果不确定`.
- Include the original node when useful. Show a destination or next node only when a sanitized response explicitly provides it; otherwise use the translated verification and do not infer routing.
- Add a final total line for confirmed, not-applied, and unknown counts. Sum monetary values only when every included value is unambiguously the same business measure and currency; label the total with that currency. Do not sum unrelated numeric fields.
- Keep elapsed time optional and secondary. Never expose the host, workcode, internal user/request/template IDs, raw SOAP, action button names, or hidden fields.
