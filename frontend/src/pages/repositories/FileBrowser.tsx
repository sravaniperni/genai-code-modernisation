import { useQuery } from '@tanstack/react-query';
import { ErrorNotice, Loading } from '../../components/ErrorNotice';
import { api } from '../../lib/api';
import { formatInt, shortSha } from '../../lib/format';
import { FileTree } from './FileTree';
import { FileViewer } from './FileViewer';
import { useExplorerParams } from './useExplorerParams';

export function FileBrowser({ repoId, gitRef }: { repoId: number; gitRef: string }) {
  const params = useExplorerParams();
  const tree = useQuery({
    queryKey: ['tree', repoId, gitRef],
    queryFn: () => api.repositories.tree(repoId, gitRef),
  });

  if (tree.isPending) return <Loading label="Loading file tree…" />;
  if (tree.isError) return <ErrorNotice error={tree.error} />;

  return (
    <div className="file-browser">
      <div className="file-tree-pane">
        <p className="muted small">
          {formatInt(tree.data.files.length)} files at{' '}
          <code>{shortSha(tree.data.snapshot.commit_sha)}</code>
        </p>
        <FileTree files={tree.data.files} selectedPath={params.path} href={params.href} />
      </div>
      <div className="file-view-pane">
        {params.path ? (
          <FileViewer
            repoId={repoId}
            gitRef={gitRef}
            path={params.path}
            line={params.line}
            end={params.end}
          />
        ) : (
          <p className="empty">Select a file in the tree to view it.</p>
        )}
      </div>
    </div>
  );
}
