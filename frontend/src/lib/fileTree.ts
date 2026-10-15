import type { TreeFile } from './types';

export interface TreeNode {
  name: string;
  /** Directory path (no trailing slash) or file path. */
  path: string;
  file: TreeFile | null;
  children: TreeNode[];
}

/** Build a nested directory tree from the flat, path-sorted file list returned by GET /tree. */
export function buildFileTree(files: TreeFile[]): TreeNode {
  const root: TreeNode = { name: '', path: '', file: null, children: [] };
  const dirs = new Map<string, TreeNode>([['', root]]);
  for (const file of files) {
    const parts = file.path.split('/');
    let parent = root;
    for (let i = 0; i < parts.length - 1; i++) {
      const dirPath = parts.slice(0, i + 1).join('/');
      let dir = dirs.get(dirPath);
      if (!dir) {
        dir = { name: parts[i]!, path: dirPath, file: null, children: [] };
        dirs.set(dirPath, dir);
        parent.children.push(dir);
      }
      parent = dir;
    }
    parent.children.push({ name: parts[parts.length - 1]!, path: file.path, file, children: [] });
  }
  sortTree(root);
  return root;
}

function sortTree(node: TreeNode): void {
  node.children.sort((a, b) => {
    const aDir = a.file === null;
    const bDir = b.file === null;
    if (aDir !== bDir) return aDir ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
  node.children.forEach(sortTree);
}

/** Every ancestor directory of a path: "a/b/c.py" -> ["a", "a/b"]. */
export function ancestorDirs(path: string): string[] {
  const parts = path.split('/');
  return parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join('/'));
}

export function allDirs(node: TreeNode, out: string[] = []): string[] {
  for (const child of node.children) {
    if (child.file === null) {
      out.push(child.path);
      allDirs(child, out);
    }
  }
  return out;
}
