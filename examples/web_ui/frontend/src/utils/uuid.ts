/**
 * Generate a UUID in both secure and non-secure browser contexts.
 *
 * `crypto.randomUUID()` is unavailable when the Web UI is served over plain
 * HTTP from a non-localhost address. `getRandomValues()` remains available in
 * those contexts, so use it to construct an RFC 4122 version 4 UUID.
 */
function fallbackUuid(): string {
	const cryptoApi = globalThis.crypto;
	const bytes = new Uint8Array(16);
	if (typeof cryptoApi?.getRandomValues === 'function') {
		cryptoApi.getRandomValues(bytes);
	} else {
		for (let index = 0; index < bytes.length; index += 1) {
			bytes[index] = Math.floor(Math.random() * 256);
		}
	}

	bytes[6] = (bytes[6] & 0x0f) | 0x40;
	bytes[8] = (bytes[8] & 0x3f) | 0x80;

	const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0'));
	return [
		hex.slice(0, 4).join(''),
		hex.slice(4, 6).join(''),
		hex.slice(6, 8).join(''),
		hex.slice(8, 10).join(''),
		hex.slice(10, 16).join(''),
	].join('-');
}

export function createUuid(): string {
	const cryptoApi = globalThis.crypto;
	if (typeof cryptoApi?.randomUUID === 'function') {
		return cryptoApi.randomUUID();
	}
	return fallbackUuid();
}

/**
 * Install a `crypto.randomUUID` compatibility implementation for libraries
 * that call the browser API directly. This must run before the application
 * creates any AgentScope SDK messages or processes streaming events.
 */
export function installRandomUuidPolyfill(): void {
	const cryptoApi = globalThis.crypto;
	if (typeof cryptoApi?.randomUUID === 'function') return;

	if (cryptoApi) {
		Object.defineProperty(cryptoApi, 'randomUUID', {
			configurable: true,
			value: fallbackUuid,
		});
		return;
	}

	Object.defineProperty(globalThis, 'crypto', {
		configurable: true,
		value: { randomUUID: fallbackUuid },
	});
}
