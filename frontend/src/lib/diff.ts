/**
 * Unified diff parser for `git diff` output (also accepts plain `diff -u` output).
 *
 * Hunk bodies are consumed by the line counts in the `@@ -a,b +c,d @@` header rather than by prefix
 * alone, so a removed line that itself starts with "--" or "++" is never mistaken for a file header.
 */

export type DiffLineType = 'context' | 'add' | 'del' | 'note';

export interface DiffLine {
  type: DiffLineType;
  content: string;
  oldNumber: number | null;
  newNumber: number | null;
}

export interface DiffHunk {
  header: string;
  oldStart: number;
  oldLines: number;
  newStart: number;
  newLines: number;
  section: string;
  lines: DiffLine[];
}

export type DiffFileStatus = 'modified' | 'added' | 'deleted' | 'renamed';

export interface DiffFile {
  oldPath: string | null;
  newPath: string | null;
  status: DiffFileStatus;
  isBinary: boolean;
  hunks: DiffHunk[];
  additions: number;
  deletions: number;
}

const HUNK_RE = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$/;
const GIT_HEADER_RE = /^diff --git (?:"?a\/(.+?)"?) (?:"?b\/(.+?)"?)$/;

/** Strip the a/ or b/ prefix git adds and any trailing timestamp `diff -u` adds after a tab. */
function cleanPath(raw: string): string | null {
  let path = raw.split('\t')[0]!.trim();
  if (path.startsWith('"') && path.endsWith('"') && path.length >= 2) path = path.slice(1, -1);
  if (path === '/dev/null') return null;
  if (path.startsWith('a/') || path.startsWith('b/')) path = path.slice(2);
  return path;
}

function newFile(oldPath: string | null = null, newPath: string | null = null): DiffFile {
  return {
    oldPath,
    newPath,
    status: 'modified',
    isBinary: false,
    hunks: [],
    additions: 0,
    deletions: 0,
  };
}

export function parseUnifiedDiff(text: string | null | undefined): DiffFile[] {
  if (!text) return [];
  const lines = text.split(/\r?\n/);
  if (lines.length && lines[lines.length - 1] === '') lines.pop();

  const files: DiffFile[] = [];
  const open = (f: DiffFile): DiffFile => {
    files.push(f);
    return f;
  };
  let file: DiffFile | null = null;
  let hunk: DiffHunk | null = null;
  let oldRemaining = 0;
  let newRemaining = 0;
  let oldNo = 0;
  let newNo = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;

    // Inside a hunk: consume exactly the number of lines the header announced.
    if (file && hunk && (oldRemaining > 0 || newRemaining > 0)) {
      const marker = line[0];
      const content = line.slice(1);
      if (marker === '+') {
        hunk.lines.push({ type: 'add', content, oldNumber: null, newNumber: newNo++ });
        file.additions++;
        newRemaining--;
        continue;
      }
      if (marker === '-') {
        hunk.lines.push({ type: 'del', content, oldNumber: oldNo++, newNumber: null });
        file.deletions++;
        oldRemaining--;
        continue;
      }
      if (marker === ' ' || line === '') {
        // Some tools strip the single space of an empty context line; treat "" as context too.
        hunk.lines.push({ type: 'context', content, oldNumber: oldNo++, newNumber: newNo++ });
        oldRemaining--;
        newRemaining--;
        continue;
      }
      if (marker === '\\') {
        hunk.lines.push({ type: 'note', content: line.slice(2), oldNumber: null, newNumber: null });
        continue;
      }
      // The body did not match the header counts: stop the hunk and read this line as a header.
      oldRemaining = 0;
      newRemaining = 0;
    }

    // "\ No newline at end of file" directly after the last line of a hunk.
    if (hunk && line.startsWith('\\')) {
      hunk.lines.push({ type: 'note', content: line.slice(2), oldNumber: null, newNumber: null });
      continue;
    }

    if (line.startsWith('diff --git ')) {
      const git = GIT_HEADER_RE.exec(line);
      file = open(newFile(git?.[1] ?? null, git?.[2] ?? null));
      hunk = null;
      continue;
    }

    const next = lines[i + 1];
    if (line.startsWith('--- ') && next !== undefined && next.startsWith('+++ ')) {
      // Plain unified diffs have no "diff --git" line; a file starts at its ---/+++ pair.
      if (!file || file.hunks.length > 0) file = open(newFile());
      hunk = null;
      file.oldPath = cleanPath(line.slice(4));
      file.newPath = cleanPath(next.slice(4));
      if (file.oldPath === null) file.status = 'added';
      else if (file.newPath === null) file.status = 'deleted';
      i++;
      continue;
    }

    const h = HUNK_RE.exec(line);
    if (h) {
      file ??= open(newFile());
      const oldStart = Number(h[1]);
      const oldLines = h[2] === undefined ? 1 : Number(h[2]);
      const newStart = Number(h[3]);
      const newLines = h[4] === undefined ? 1 : Number(h[4]);
      hunk = {
        header: line,
        oldStart,
        oldLines,
        newStart,
        newLines,
        section: h[5] ?? '',
        lines: [],
      };
      file.hunks.push(hunk);
      oldRemaining = oldLines;
      newRemaining = newLines;
      oldNo = oldStart;
      newNo = newStart;
      continue;
    }

    if (!file) continue;
    if (line.startsWith('new file mode')) file.status = 'added';
    else if (line.startsWith('deleted file mode')) file.status = 'deleted';
    else if (line.startsWith('rename from ')) {
      file.status = 'renamed';
      file.oldPath = line.slice('rename from '.length);
    } else if (line.startsWith('rename to ')) {
      file.status = 'renamed';
      file.newPath = line.slice('rename to '.length);
    } else if (line.startsWith('Binary files ') || line === 'GIT binary patch') {
      file.isBinary = true;
    }
  }

  for (const f of files) {
    if (f.status === 'added') f.oldPath = null;
    if (f.status === 'deleted') f.newPath = null;
  }
  return files;
}

export function displayPath(file: DiffFile): string {
  if (file.status === 'renamed' && file.oldPath && file.newPath && file.oldPath !== file.newPath) {
    return `${file.oldPath} → ${file.newPath}`;
  }
  return file.newPath ?? file.oldPath ?? '(unknown file)';
}

export interface SplitRow {
  kind: 'line' | 'note';
  left: DiffLine | null;
  right: DiffLine | null;
}

/**
 * Pair a hunk's lines for a side-by-side (before | after) view: within each run of changes, removed
 * lines line up with added lines; context lines appear on both sides.
 */
export function toSplitRows(hunk: DiffHunk): SplitRow[] {
  const rows: SplitRow[] = [];
  let dels: DiffLine[] = [];
  let adds: DiffLine[] = [];
  const flush = () => {
    const n = Math.max(dels.length, adds.length);
    for (let i = 0; i < n; i++)
      rows.push({ kind: 'line', left: dels[i] ?? null, right: adds[i] ?? null });
    dels = [];
    adds = [];
  };
  for (const line of hunk.lines) {
    if (line.type === 'del') dels.push(line);
    else if (line.type === 'add') adds.push(line);
    else {
      flush();
      if (line.type === 'context') rows.push({ kind: 'line', left: line, right: line });
      else rows.push({ kind: 'note', left: line, right: null });
    }
  }
  flush();
  return rows;
}

export function diffStats(files: DiffFile[]): {
  files: number;
  additions: number;
  deletions: number;
} {
  return files.reduce(
    (acc, f) => ({
      files: acc.files + 1,
      additions: acc.additions + f.additions,
      deletions: acc.deletions + f.deletions,
    }),
    { files: 0, additions: 0, deletions: 0 },
  );
}
