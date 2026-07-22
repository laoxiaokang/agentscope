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
