import { describe, expect, it } from 'vitest';
import { diffStats, displayPath, parseUnifiedDiff, toSplitRows } from './diff';

const MODIFY = `diff --git a/src/inventory/pricing.py b/src/inventory/pricing.py
index 3b18e51..a9c2f04 100644
--- a/src/inventory/pricing.py
+++ b/src/inventory/pricing.py
@@ -12,7 +12,7 @@ def apply_discount(price: float, percent: float) -> float:
     """Return price reduced by percent percent, never below zero."""
     if percent < 0 or percent > 100:
         raise ValueError("percent must be between 0 and 100")
-    return round(price - price * percent / 1000, 2)
+    return round(price - price * percent / 100, 2)
 
 
 def order_total(items, discount_percent=0.0):
`;

describe('parseUnifiedDiff', () => {
  it('parses a modified file with old and new line numbers', () => {
    const [file, ...rest] = parseUnifiedDiff(MODIFY);
    expect(rest).toHaveLength(0);
    expect(file).toMatchObject({
      oldPath: 'src/inventory/pricing.py',
      newPath: 'src/inventory/pricing.py',
      status: 'modified',
      additions: 1,
      deletions: 1,
      isBinary: false,
    });
    const hunk = file!.hunks[0]!;
    expect(hunk).toMatchObject({ oldStart: 12, oldLines: 7, newStart: 12, newLines: 7 });
    expect(hunk.section).toBe('def apply_discount(price: float, percent: float) -> float:');
    const del = hunk.lines.find((l) => l.type === 'del')!;
    const add = hunk.lines.find((l) => l.type === 'add')!;
    expect(del).toEqual({
      type: 'del',
      content: '    return round(price - price * percent / 1000, 2)',
      oldNumber: 15,
      newNumber: null,
    });
    expect(add).toEqual({
      type: 'add',
      content: '    return round(price - price * percent / 100, 2)',
      oldNumber: null,
      newNumber: 15,
    });
    const last = hunk.lines[hunk.lines.length - 1]!;
    expect(last).toMatchObject({ type: 'context', oldNumber: 18, newNumber: 18 });
    // The blank context lines (" ") keep their numbering.
    expect(hunk.lines.filter((l) => l.type === 'context' && l.content === '')).toHaveLength(2);
  });

  it('recognises added, deleted and renamed files', () => {
    const diff = [
      'diff --git a/tests/test_new.py b/tests/test_new.py',
      'new file mode 100644',
      'index 0000000..e69de29',
      '--- /dev/null',
      '+++ b/tests/test_new.py',
      '@@ -0,0 +1,2 @@',
      '+def test_it():',
      '+    assert True',
      'diff --git a/old.txt b/old.txt',
      'deleted file mode 100644',
      '--- a/old.txt',
      '+++ /dev/null',
      '@@ -1 +0,0 @@',
      '-gone',
      'diff --git a/a.py b/b.py',
      'similarity index 100%',
      'rename from a.py',
      'rename to b.py',
      'diff --git a/logo.png b/logo.png',
      'Binary files a/logo.png and b/logo.png differ',
    ].join('\n');
    const files = parseUnifiedDiff(diff);
    expect(files.map((f) => f.status)).toEqual(['added', 'deleted', 'renamed', 'modified']);
    expect(files[0]).toMatchObject({ oldPath: null, newPath: 'tests/test_new.py', additions: 2 });
    expect(files[0]!.hunks[0]!.lines.map((l) => l.newNumber)).toEqual([1, 2]);
    expect(files[1]).toMatchObject({ oldPath: 'old.txt', newPath: null, deletions: 1 });
    expect(files[1]!.hunks[0]).toMatchObject({ oldStart: 1, oldLines: 1, newLines: 0 });
    expect(displayPath(files[2]!)).toBe('a.py → b.py');
    expect(files[2]!.hunks).toHaveLength(0);
    expect(files[3]!.isBinary).toBe(true);
  });

  it('uses hunk counts, so removed lines that look like headers stay content', () => {
    const diff = [
      'diff --git a/schema.sql b/schema.sql',
      '--- a/schema.sql',
      '+++ b/schema.sql',
      '@@ -1,3 +1,3 @@',
      '--- old comment',
      '+++ new comment',
      ' select 1;',
      '-drop table x;',
      '+drop table y;',
    ].join('\n');
    const files = parseUnifiedDiff(diff);
    expect(files).toHaveLength(1);
    const lines = files[0]!.hunks[0]!.lines;
    expect(lines.slice(0, 2)).toEqual([
      { type: 'del', content: '-- old comment', oldNumber: 1, newNumber: null },
      { type: 'add', content: '++ new comment', oldNumber: null, newNumber: 1 },
    ]);
    // -1,3 +1,3: two removals, two additions and one context line, all in one hunk of one file.
    expect(lines.map((l) => l.type)).toEqual(['del', 'add', 'context', 'del', 'add']);
    expect(files[0]).toMatchObject({ additions: 2, deletions: 2 });
  });

  it('keeps "no newline at end of file" markers as notes and handles several hunks', () => {
    const diff = [
      'diff --git a/x.py b/x.py',
      '--- a/x.py',
      '+++ b/x.py',
      '@@ -1,2 +1,2 @@',
      ' a = 1',
      '-b = 2',
      '\\ No newline at end of file',
      '+b = 3',
      '\\ No newline at end of file',
      '@@ -10 +10,2 @@ class K:',
      ' x',
      '+y',
    ].join('\n');
    const [file] = parseUnifiedDiff(diff);
    expect(file!.hunks).toHaveLength(2);
    const notes = file!.hunks[0]!.lines.filter((l) => l.type === 'note');
    expect(notes.map((n) => n.content)).toEqual([
      'No newline at end of file',
      'No newline at end of file',
    ]);
    expect(file!.hunks[1]).toMatchObject({ oldStart: 10, oldLines: 1, newStart: 10, newLines: 2 });
    expect(diffStats([file!])).toEqual({ files: 1, additions: 2, deletions: 1 });
  });

  it('accepts plain diff -u output without a git header', () => {
    const diff = [
      '--- before/app.py\t2026-10-15 10:00:00',
      '+++ after/app.py\t2026-10-15 10:01:00',
      '@@ -1 +1 @@',
      '-print("hi")',
      '+print("hello")',
    ].join('\n');
    const [file] = parseUnifiedDiff(diff);
    expect(file).toMatchObject({ oldPath: 'before/app.py', newPath: 'after/app.py', additions: 1 });
  });

  it('returns no files for empty input', () => {
    expect(parseUnifiedDiff('')).toEqual([]);
    expect(parseUnifiedDiff(null)).toEqual([]);
    expect(parseUnifiedDiff(undefined)).toEqual([]);
  });
});

describe('toSplitRows', () => {
  it('pairs removed and added lines side by side and mirrors context', () => {
    const diff = [
      'diff --git a/f b/f',
      '--- a/f',
      '+++ b/f',
      '@@ -1,4 +1,3 @@',
      ' keep',
      '-old 1',
      '-old 2',
      '+new 1',
      ' tail',
    ].join('\n');
    const rows = toSplitRows(parseUnifiedDiff(diff)[0]!.hunks[0]!);
    expect(rows.map((r) => [r.left?.content ?? null, r.right?.content ?? null])).toEqual([
      ['keep', 'keep'],
      ['old 1', 'new 1'],
      ['old 2', null],
      ['tail', 'tail'],
    ]);
  });
});
