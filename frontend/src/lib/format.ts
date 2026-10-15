/** Display helpers. Missing values are always shown as such, never as zero. */

const dateTime = new Intl.DateTimeFormat(undefined, {
  year: 'numeric',
  month: 'short',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});
const timeOnly = new Intl.DateTimeFormat(undefined, {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
});
const integer = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });

export const NOT_AVAILABLE = '—';

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return NOT_AVAILABLE;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : dateTime.format(date);
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return NOT_AVAILABLE;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : timeOnly.format(date);
}

export function formatInt(value: number | null | undefined): string {
  return value === null || value === undefined ? NOT_AVAILABLE : integer.format(value);
}

/** 0.8125 -> "81.3%" */
export function formatPercent(rate: number | null | undefined, digits = 1): string {
  if (rate === null || rate === undefined) return NOT_AVAILABLE;
  return `${(rate * 100).toFixed(digits)}%`;
}

export function formatDurationMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return NOT_AVAILABLE;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return formatSeconds(ms / 1000);
}

export function formatSeconds(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return NOT_AVAILABLE;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 2 : 1)} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds - minutes * 60);
  return `${minutes} min ${rest} s`;
}

/** Cost is unknown (null) when the model price is not configured; that is not the same as free. */
export function formatCost(usd: number | null | undefined): string {
  if (usd === null || usd === undefined) return 'not applicable';
  return `$${usd.toFixed(usd < 1 ? 4 : 2)}`;
}

export function shortSha(sha: string | null | undefined, length = 10): string {
  return sha ? sha.slice(0, length) : NOT_AVAILABLE;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return NOT_AVAILABLE;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function humanize(value: string): string {
  return value.replace(/_/g, ' ');
}

export function yesNo(value: boolean | null | undefined): string {
  if (value === null || value === undefined) return NOT_AVAILABLE;
  return value ? 'yes' : 'no';
}
