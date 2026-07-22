# Frontend Bypass Permission Default Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist `bypass` for sessions created by the Web UI while leaving backend and existing-session defaults unchanged.

**Architecture:** Put the frontend default and display fallback in a small permission utility. Put the two-request create/update orchestration in a pure async helper, then call it from `useSessions`; this keeps React code thin and makes request order and partial-failure behavior testable with Node's built-in test runner.

**Tech Stack:** TypeScript, React 19, Node 22 `node:test`, existing session API

---

### Task 1: Specify permission default and session creation behavior

**Files:**
- Create: `examples/web_ui/frontend/tests/frontendPermissionDefault.test.ts`
- Modify: `examples/web_ui/frontend/package.json`

- [x] **Step 1: Add focused tests for the frontend default**

```typescript
import assert from 'node:assert/strict';
import test from 'node:test';

import {
	DEFAULT_FRONTEND_PERMISSION_MODE,
	resolveFrontendPermissionMode,
} from '../src/lib/permissionDefaults.ts';
import { createSessionWithDefaultPermission } from '../src/hooks/createSessionWithDefaultPermission.ts';

test('missing permission state falls back to bypass', () => {
	assert.equal(DEFAULT_FRONTEND_PERMISSION_MODE, 'bypass');
	assert.equal(resolveFrontendPermissionMode(undefined), 'bypass');
	assert.equal(resolveFrontendPermissionMode('explore'), 'explore');
});

test('new frontend sessions persist bypass before refetching', async () => {
	const calls: unknown[] = [];
	const result = await createSessionWithDefaultPermission(
		{
			create: async (body) => {
				calls.push(['create', body]);
				return { session_id: 'session-1' };
			},
			update: async (sessionId, agentId, body) => {
				calls.push(['update', sessionId, agentId, body]);
			},
		},
		{ agent_id: 'agent-1' },
		async () => {
			calls.push(['refetch']);
		},
	);

	assert.deepEqual(result, { session_id: 'session-1' });
	assert.deepEqual(calls, [
		['create', { agent_id: 'agent-1' }],
		['update', 'session-1', 'agent-1', { permission_mode: 'bypass' }],
		['refetch'],
	]);
});

test('an update failure refreshes state and preserves the update error', async () => {
	const updateError = new Error('permission update failed');
	let refetched = false;

	await assert.rejects(
		createSessionWithDefaultPermission(
			{
				create: async () => ({ session_id: 'session-2' }),
				update: async () => {
					throw updateError;
				},
			},
			{ agent_id: 'agent-1' },
			async () => {
				refetched = true;
			},
		),
		(error) => error === updateError,
	);
	assert.equal(refetched, true);
});
```

- [x] **Step 2: Add the dependency-free test command**

```json
"test": "node --test tests/frontendPermissionDefault.test.ts"
```

- [x] **Step 3: Run the tests and verify the missing modules fail**

Run: `npm test`

Expected: FAIL because `permissionDefaults.ts` and
`createSessionWithDefaultPermission.ts` do not exist.

### Task 2: Implement the frontend permission policy

**Files:**
- Create: `examples/web_ui/frontend/src/lib/permissionDefaults.ts`
- Create: `examples/web_ui/frontend/src/hooks/createSessionWithDefaultPermission.ts`
- Modify: `examples/web_ui/frontend/src/hooks/useSessions.ts`
- Modify: `examples/web_ui/frontend/src/pages/chat/ChatViewport.tsx`
- Test: `examples/web_ui/frontend/tests/frontendPermissionDefault.test.ts`

- [x] **Step 1: Add the shared default and fallback resolver**

```typescript
import type { PermissionMode } from '../api/types.ts';

export const DEFAULT_FRONTEND_PERMISSION_MODE: PermissionMode = 'bypass';

export function resolveFrontendPermissionMode(
	mode: PermissionMode | null | undefined,
): PermissionMode {
	return mode ?? DEFAULT_FRONTEND_PERMISSION_MODE;
}
```

- [x] **Step 2: Add the create/update orchestration helper**

```typescript
import type {
	CreateSessionRequest,
	CreateSessionResponse,
	UpdateSessionRequest,
} from '../api/types.ts';
import { DEFAULT_FRONTEND_PERMISSION_MODE } from '../lib/permissionDefaults.ts';

interface SessionCreationApi {
	create(body: CreateSessionRequest): Promise<CreateSessionResponse>;
	update(
		sessionId: string,
		agentId: string,
		body: UpdateSessionRequest,
	): Promise<unknown>;
}

export async function createSessionWithDefaultPermission(
	api: SessionCreationApi,
	body: CreateSessionRequest,
	refetch: () => Promise<unknown>,
): Promise<CreateSessionResponse> {
	const response = await api.create(body);
	try {
		await api.update(response.session_id, body.agent_id, {
			permission_mode: DEFAULT_FRONTEND_PERMISSION_MODE,
		});
	} catch (error) {
		try {
			await refetch();
		} catch {
			// Preserve the permission update failure for the caller.
		}
		throw error;
	}
	await refetch();
	return response;
}
```

- [x] **Step 3: Use the helper in `useSessions`**

Add the import:

```typescript
import { createSessionWithDefaultPermission } from './createSessionWithDefaultPermission.ts';
```

Replace the create callback with:

```typescript
const create = useCallback(
	async (body: CreateSessionRequest) =>
		createSessionWithDefaultPermission(sessionApi, body, refetch),
	[refetch],
);
```

- [x] **Step 4: Use the shared fallback in `ChatViewport`**

Import the permission type and helpers, initialize the state with
`DEFAULT_FRONTEND_PERMISSION_MODE`, and replace the `mode ?? 'default'`
fallback with `resolveFrontendPermissionMode(mode)` while leaving loaded
session modes authoritative.

- [x] **Step 5: Run the focused test and verify it passes**

Run: `npm test`

Expected: three passing tests.

### Task 3: Verify the frontend

**Files:**
- Verify: `examples/web_ui/frontend/package.json`
- Verify: `examples/web_ui/frontend/src/hooks/useSessions.ts`
- Verify: `examples/web_ui/frontend/src/pages/chat/ChatViewport.tsx`
- Verify: `examples/web_ui/frontend/src/hooks/createSessionWithDefaultPermission.ts`
- Verify: `examples/web_ui/frontend/src/lib/permissionDefaults.ts`

- [x] **Step 1: Run TypeScript and production build verification**

Run: `npm run build`

Expected: TypeScript and Vite build complete successfully.

- [x] **Step 2: Run lint on the changed TypeScript files**

Run: `npx eslint src/hooks/useSessions.ts src/hooks/createSessionWithDefaultPermission.ts src/lib/permissionDefaults.ts src/pages/chat/ChatViewport.tsx tests/frontendPermissionDefault.test.ts`

Expected: command exits without errors.

- [x] **Step 3: Check whitespace and persisted default references**

Run: `git diff --check -- examples/web_ui/frontend/package.json examples/web_ui/frontend/src/hooks/useSessions.ts examples/web_ui/frontend/src/hooks/createSessionWithDefaultPermission.ts examples/web_ui/frontend/src/lib/permissionDefaults.ts examples/web_ui/frontend/src/pages/chat/ChatViewport.tsx examples/web_ui/frontend/tests/frontendPermissionDefault.test.ts`

Expected: no whitespace errors, and the frontend default is defined once as
`bypass`.

No Git commit is created, per the user's instruction.
