import { useCallback } from 'react';
import { useSearchParams } from 'react-router';
import type { SearchMode } from '../../lib/types';

export const EXPLORER_TABS = ['files', 'search', 'findings', 'commits', 'snapshots'] as const;
export type ExplorerTab = (typeof EXPLORER_TABS)[number];
const MODES: SearchMode[] = ['text', 'regex', 'symbol', 'references'];

type ParamChanges = Record<string, string | number | null | undefined>;

function toInt(value: string | null): number | null {
  if (!value) return null;
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** Explorer state lives in the URL so files, lines and searches can be linked and bookmarked. */
export function useExplorerParams() {
  const [params, setParams] = useSearchParams();
  const rawTab = params.get('tab');
  const tab: ExplorerTab = (EXPLORER_TABS as readonly string[]).includes(rawTab ?? '')
    ? (rawTab as ExplorerTab)
    : 'files';
  const rawMode = params.get('mode');
  const mode: SearchMode = MODES.includes(rawMode as SearchMode) ? (rawMode as SearchMode) : 'text';

  const href = useCallback(
    (changes: ParamChanges): string => {
      const next = new URLSearchParams(params);
      for (const [key, value] of Object.entries(changes)) {
        if (value === null || value === undefined || value === '') next.delete(key);
        else next.set(key, String(value));
      }
      return `?${next.toString()}`;
    },
    [params],
  );

  const update = useCallback(
    (changes: ParamChanges) => {
      setParams((prev) => {
        const next = new URLSearchParams(prev);
        for (const [key, value] of Object.entries(changes)) {
          if (value === null || value === undefined || value === '') next.delete(key);
          else next.set(key, String(value));
        }
        return next;
      });
    },
    [setParams],
  );

  return {
    tab,
    ref: params.get('ref') ?? '',
    path: params.get('path'),
    line: toInt(params.get('line')),
    end: toInt(params.get('end')),
    q: params.get('q') ?? '',
    mode,
    href,
    update,
  };
}

/** Link to a file location in the explorer, keeping the selected ref. */
export function fileHref(
  href: (changes: ParamChanges) => string,
  path: string,
  start?: number | null,
  end?: number | null,
): string {
  return href({ tab: 'files', path, line: start ?? null, end: end && end !== start ? end : null });
}
