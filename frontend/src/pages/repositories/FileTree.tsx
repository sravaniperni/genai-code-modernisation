import { useId, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { allDirs, ancestorDirs, buildFileTree, type TreeNode } from '../../lib/fileTree';
import type { TreeFile } from '../../lib/types';
import { fileHref } from './useExplorerParams';

type Href = (changes: Record<string, string | number | null | undefined>) => string;

function FileBadges({ file }: { file: TreeFile }) {
  return (
    <>
      {file.is_test ? <span className="badge tone-info badge-small">test</span> : null}
      {file.is_config ? <span className="badge tone-attention badge-small">config</span> : null}
    </>
  );
}

function Node({
  node,
  expanded,
  toggle,
  selectedPath,
  href,
}: {
  node: TreeNode;
  expanded: Set<string>;
  toggle: (path: string) => void;
  selectedPath: string | null;
  href: Href;
}) {
  if (node.file) {
    const selected = node.path === selectedPath;
    return (
      <li>
        <Link
          to={fileHref(href, node.path)}
          className={selected ? 'tree-file selected' : 'tree-file'}
          aria-current={selected ? 'true' : undefined}
          title={node.path}
        >
          <span className="tree-name">{node.name}</span>
          <FileBadges file={node.file} />
        </Link>
      </li>
    );
  }
  const open = expanded.has(node.path);
  return (
    <li>
      <button
        type="button"
        className="tree-dir"
        aria-expanded={open}
        onClick={() => toggle(node.path)}
      >
        <span aria-hidden="true" className="tree-caret">
          {open ? '▾' : '▸'}
        </span>
        {node.name}/
      </button>
      {open ? (
        <ul>
          {node.children.map((child) => (
            <Node
              key={child.path}
              node={child}
              expanded={expanded}
              toggle={toggle}
              selectedPath={selectedPath}
              href={href}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function FileTree({
  files,
  selectedPath,
  href,
}: {
  files: TreeFile[];
  selectedPath: string | null;
  href: Href;
}) {
  const id = useId();
  const root = useMemo(() => buildFileTree(files), [files]);
  const [filter, setFilter] = useState('');
  // Small repositories start fully expanded; larger ones show the path to the selected file.
  const [expanded, setExpanded] = useState<Set<string>>(
    () => new Set(files.length <= 200 ? allDirs(root) : ancestorDirs(selectedPath ?? '')),
  );
  const toggle = (path: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  const needle = filter.trim().toLowerCase();
  const matches = needle ? files.filter((f) => f.path.toLowerCase().includes(needle)) : [];

  return (
    <nav aria-label="File tree" className="file-tree">
      <div className="field">
        <label htmlFor={`${id}-filter`}>Filter files</label>
        <input
          id={`${id}-filter`}
          type="search"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="path contains…"
        />
      </div>
      {needle ? (
        matches.length === 0 ? (
          <p className="empty">No files match “{filter}”.</p>
        ) : (
          <ul className="tree-flat">
            {matches.map((file) => (
              <li key={file.path}>
                <Link
                  to={fileHref(href, file.path)}
                  className={file.path === selectedPath ? 'tree-file selected' : 'tree-file'}
                  aria-current={file.path === selectedPath ? 'true' : undefined}
                >
                  <span className="tree-name">{file.path}</span>
                  <FileBadges file={file} />
                </Link>
              </li>
            ))}
          </ul>
        )
      ) : files.length === 0 ? (
        <p className="empty">The index contains no files.</p>
      ) : (
        <ul className="tree-root">
          {root.children.map((child) => (
            <Node
              key={child.path}
              node={child}
              expanded={expanded}
              toggle={toggle}
              selectedPath={selectedPath}
              href={href}
            />
          ))}
        </ul>
      )}
    </nav>
  );
}
