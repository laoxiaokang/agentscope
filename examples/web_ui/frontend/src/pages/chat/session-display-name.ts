interface SessionDisplayRecord {
	id: string;
	created_at: string;
	config: {
		name: string;
	};
}

const GENERATED_NAME_PATTERN = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/;
const TIMEZONE_SUFFIX_PATTERN = /(?:Z|[+-]\d{2}:?\d{2})$/i;
const LEGACY_TIMESTAMP_TOLERANCE_MS = 5_000;

function parseServerTimestamp(value: string): Date | null {
	const normalized = TIMEZONE_SUFFIX_PATTERN.test(value) ? value : `${value}Z`;
	const date = new Date(normalized);
	return Number.isNaN(date.getTime()) ? null : date;
}

function parseGeneratedName(value: string): Date | null {
	if (!GENERATED_NAME_PATTERN.test(value)) return null;
	return parseServerTimestamp(value.replace(' ', 'T'));
}

function formatTimestamp(date: Date, timeZone?: string): string {
	const formatter = new Intl.DateTimeFormat('en-CA', {
		year: 'numeric',
		month: '2-digit',
		day: '2-digit',
		hour: '2-digit',
		minute: '2-digit',
		second: '2-digit',
		hourCycle: 'h23',
		...(timeZone ? { timeZone } : {}),
	});
	const parts = Object.fromEntries(
		formatter
			.formatToParts(date)
			.filter((part) => part.type !== 'literal')
			.map((part) => [part.type, part.value]),
	);

	return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}

/**
 * The service uses the container's wall clock for automatically generated
 * session names. Detect those names by comparing them with created_at, then
 * render the creation time in the browser's timezone. Timezone-aware scheduler
 * names and manually renamed sessions pass through unchanged.
 */
export function getSessionDisplayName(
	session: SessionDisplayRecord,
	timeZone?: string,
): string {
	const name = session.config.name || session.id;
	const generatedAt = parseGeneratedName(name);
	const createdAt = parseServerTimestamp(session.created_at);
	if (!generatedAt || !createdAt) return name;

	const isLegacyUtcName =
		Math.abs(generatedAt.getTime() - createdAt.getTime()) <=
		LEGACY_TIMESTAMP_TOLERANCE_MS;
	return isLegacyUtcName ? formatTimestamp(createdAt, timeZone) : name;
}
