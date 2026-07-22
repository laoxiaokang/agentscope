import type { PermissionMode } from '../api/types.ts';

export const DEFAULT_FRONTEND_PERMISSION_MODE: PermissionMode = 'bypass';

export function resolveFrontendPermissionMode(
	mode: PermissionMode | null | undefined,
): PermissionMode {
	return mode ?? DEFAULT_FRONTEND_PERMISSION_MODE;
}
