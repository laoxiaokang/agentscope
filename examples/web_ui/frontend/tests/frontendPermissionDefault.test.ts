import assert from 'node:assert/strict';
import test from 'node:test';

import { createSessionWithDefaultPermission } from '../src/hooks/createSessionWithDefaultPermission.ts';
import {
	DEFAULT_FRONTEND_PERMISSION_MODE,
	resolveFrontendPermissionMode,
} from '../src/lib/permissionDefaults.ts';

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
