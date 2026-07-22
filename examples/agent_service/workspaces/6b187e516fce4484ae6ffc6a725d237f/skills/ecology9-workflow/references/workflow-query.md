# Ecology Workflow Query Routing

Use the Python script as the canonical implementation for the local deployment's read-only `WorkflowService` queries:

- `scripts/ecology_workflow_query.py` is the primary entrypoint and uses only the Python standard library.
- `scripts/ecology_workflow_query.ps1` is a thin PowerShell wrapper that forwards validated arguments to the Python script and preserves its JSON and exit code.

Both entrypoints therefore read `config.local.json`, map the supplied workcode once, reuse one HTTP connection, skip WSDL discovery, and fetch list pages only when requested. Do not run both during a normal query.

## Command

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ecology_workflow_query.ps1 `
  -Workcode {WORKCODE} -Mode todo
```

```bash
python scripts/ecology_workflow_query.py --workcode {WORKCODE} --mode todo
```

Add `-IncludeItems` or `--include-items` only when the user requests workflow details. Set page size or maximum items only when the defaults are unsuitable.

## Mode Routing

| User intent | Mode | Count operation | List operation |
|---|---|---|---|
| pending, todo, waiting for me | `todo` | `getToDoWorkflowRequestCount` | `getToDoWorkflowRequestList` |
| started by me, my requests | `started` | `getMyWorkflowRequestCount` | `getMyWorkflowRequestList` |
| handled by me, completed actions | `handled` | `getHendledWorkflowRequestCount` | `getHendledWorkflowRequestList` |
| fully processed or archived | `processed` | `getProcessedWorkflowRequestCount` | `getProcessedWorkflowRequestList` |
| templates I can start | `creatable` | `getCreateWorkflowTypeCount` | `getCreateWorkflowTypeList` |
| several counts in one request | `summary` | all four standard count operations | none |

`getHendled...` is the method name exposed by the installed WSDL; preserve its spelling.

## Fixed Query Flow

1. Read and validate `oaBaseUrl` from `config.local.json`.
2. Send every SOAP request with `Accept: text/html,application/xhtml+xml`.
3. Call `getUserId("workcode", value)` once. Keep the returned user ID in memory only.
4. Call the selected count operation.
5. Return immediately when only a count was requested or the count is zero.
6. When `-IncludeItems` is present, page the matching list operation with the known count.
7. Return sanitized JSON without the host, workcode, internal user ID, raw SOAP, or SSO data.

For `creatable`, use `getCreateWorkflowTypeCount` plus `getCreateWorkflowTypeList`. The local deployment's `getCreateWorkflowCount` returns unreliable counts and must not be used. The fast path returns authorized category and template names without making one request per category.

## Output

Standard modes return:

```json
{
  "mode": "todo",
  "count": 0,
  "itemsIncluded": false,
  "returned": 0,
  "truncated": false,
  "queriedAt": "YYYY-MM-DD HH:mm:ss",
  "elapsedMs": 0,
  "items": []
}
```

`summary` returns `todo`, `started`, `handled`, and `processed` counts after one account mapping. `creatable` items contain only `category` and `workflowName`.

## Security

- Require explicit authorization for live OA calls and for the employee placed in scope.
- Treat the workcode as an identifier, not proof of identity.
- Never store workcodes, resolved user IDs, raw responses, or workflow data in the skill directory.
- Keep this script read-only. Do not add state-changing SOAP operations to it.
