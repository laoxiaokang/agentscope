# Frontend Bypass Permission Default Design

## Goal

Make sessions created from the Web UI use `bypass` as their persisted
permission mode without changing the backend default for API clients, scripts,
scheduled tasks, or subagents.

## Creation Flow

The frontend session hook will create the session first and then immediately
update that session with `permission_mode: "bypass"`. The session list is
refetched only after both requests finish, so consumers normally observe the
persisted mode rather than the backend's temporary `default` value.

This remains a frontend-only policy. Existing sessions retain their stored
permission mode, including `default`, `accept_edits`, or `explore`.

## Display State

`ChatViewport` will use `bypass` as its initial and missing-context fallback
value. Once a session view loads, its persisted `permission_context.mode`
remains authoritative. This avoids displaying `default` while a newly created
session is loading without overriding existing sessions.

## Failure Behavior

Session creation and the permission update are two HTTP requests and therefore
are not atomic. If creation succeeds but the update fails, the hook will
refetch the session list before rethrowing the error. The created session will
remain visible with the backend's safe `default` permission rather than being
silently presented as `bypass`.

## Security Boundary

`bypass` skips normal permission and safety prompts except explicit deny/ask
rules and tool-level denial. The UI should persist this value only because the
operator explicitly selected it as the frontend default; backend defaults and
unattended schedules remain unchanged.

## Verification

Focused frontend tests will verify that session creation is followed by the
`bypass` update, that the list is refreshed after success and partial failure,
and that existing session modes continue to override the display fallback.
The frontend type checker and relevant test command will be run afterward.
