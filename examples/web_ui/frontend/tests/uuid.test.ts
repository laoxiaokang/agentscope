import assert from 'node:assert/strict';
import test from 'node:test';

import { EventType } from '@agentscope-ai/agentscope/event';
import { appendEvent, AssistantMsg, UserMsg } from '@agentscope-ai/agentscope/message';

import { createUuid, installRandomUuidPolyfill } from '../src/utils/uuid.ts';

const UUID_V4_PATTERN =
	/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

test('createUuid returns an RFC 4122 version 4 UUID', () => {
	assert.match(createUuid(), UUID_V4_PATTERN);
});

test('createUuid works when randomUUID is unavailable over HTTP', () => {
	const originalCrypto = Object.getOwnPropertyDescriptor(globalThis, 'crypto');

	try {
		Object.defineProperty(globalThis, 'crypto', {
			configurable: true,
			value: {
				getRandomValues(bytes: Uint8Array) {
					bytes.fill(0xab);
					return bytes;
				},
			},
		});

		assert.equal(createUuid(), 'abababab-abab-4bab-abab-abababababab');
	} finally {
		if (originalCrypto) {
			Object.defineProperty(globalThis, 'crypto', originalCrypto);
		} else {
			delete (globalThis as { crypto?: Crypto }).crypto;
		}
	}
});

test('createUuid has a fallback when Web Crypto is unavailable', () => {
	const originalCrypto = Object.getOwnPropertyDescriptor(globalThis, 'crypto');
	const originalRandom = Math.random;

	try {
		Object.defineProperty(globalThis, 'crypto', {
			configurable: true,
			value: undefined,
		});
		Math.random = () => 0.5;

		assert.equal(createUuid(), '80808080-8080-4080-8080-808080808080');
	} finally {
		Math.random = originalRandom;
		if (originalCrypto) {
			Object.defineProperty(globalThis, 'crypto', originalCrypto);
		} else {
			delete (globalThis as { crypto?: Crypto }).crypto;
		}
	}
});

test('polyfill supports AgentScope SDK message and tool-result UUIDs over HTTP', () => {
	const originalCrypto = Object.getOwnPropertyDescriptor(globalThis, 'crypto');

	try {
		Object.defineProperty(globalThis, 'crypto', {
			configurable: true,
			value: {
				getRandomValues(bytes: Uint8Array) {
					bytes.fill(0xcd);
					return bytes;
				},
			},
		});

		installRandomUuidPolyfill();
		assert.equal(typeof globalThis.crypto.randomUUID, 'function');

		const user = UserMsg({ name: 'user', content: 'hello' });
		assert.match(user.id, UUID_V4_PATTERN);
		assert.match(user.content[0].id, UUID_V4_PATTERN);

		const reply = AssistantMsg({ id: 'reply-1', name: 'assistant', content: [] });
		const baseEvent = {
			id: 'event-1',
			created_at: new Date().toISOString(),
			reply_id: reply.id,
			tool_call_id: 'tool-1',
		};
		appendEvent(reply, {
			...baseEvent,
			type: EventType.TOOL_RESULT_START,
			tool_call_name: 'test-tool',
		});
		appendEvent(reply, {
			...baseEvent,
			type: EventType.TOOL_RESULT_TEXT_DELTA,
			delta: 'result',
		});
		appendEvent(reply, {
			...baseEvent,
			type: EventType.TOOL_RESULT_DATA_DELTA,
			media_type: 'text/plain',
			data: 'cmVzdWx0',
		});

		const result = reply.content.find((block) => block.type === 'tool_result');
		assert.ok(result && result.type === 'tool_result' && Array.isArray(result.output));
		for (const block of result.output) {
			assert.match(block.id, UUID_V4_PATTERN);
		}
	} finally {
		if (originalCrypto) {
			Object.defineProperty(globalThis, 'crypto', originalCrypto);
		} else {
			delete (globalThis as { crypto?: Crypto }).crypto;
		}
	}
});
