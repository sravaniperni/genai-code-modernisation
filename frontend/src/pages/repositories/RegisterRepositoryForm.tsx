import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useId, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';
import { ErrorNotice } from '../../components/ErrorNotice';
import { api } from '../../lib/api';
import type { RepositoryCreate } from '../../lib/types';

export function RegisterRepositoryForm() {
  const id = useId();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [kind, setKind] = useState<'local' | 'github'>('local');
  const [source, setSource] = useState('');
  const [name, setName] = useState('');
  const settings = useQuery({
    queryKey: ['settings'],
    queryFn: api.settings.get,
    staleTime: 60_000,
  });

  const register = useMutation({
    mutationFn: (body: RepositoryCreate) => api.repositories.create(body),
    onSuccess: (repo) => {
      void queryClient.invalidateQueries({ queryKey: ['repositories'] });
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] });
      setSource('');
      setName('');
      void navigate(`/repositories/${repo.id}`);
    },
  });

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    register.mutate({ kind, source: source.trim(), ...(name.trim() ? { name: name.trim() } : {}) });
  };

  const roots = settings.data?.repositories.allowed_local_roots ?? [];
  const allowedGithub = settings.data?.github.allowed_repositories ?? [];

  return (
    <form onSubmit={onSubmit} className="form" aria-labelledby={`${id}-title`} noValidate>
      <h2 id={`${id}-title`}>Register a repository</h2>
      <fieldset className="radio-row">
        <legend>Source</legend>
        <label>
          <input
            type="radio"
            name={`${id}-kind`}
            value="local"
            checked={kind === 'local'}
            onChange={() => setKind('local')}
          />
          Local git repository
        </label>
        <label>
          <input
            type="radio"
            name={`${id}-kind`}
            value="github"
            checked={kind === 'github'}
            onChange={() => setKind('github')}
          />
          GitHub
        </label>
      </fieldset>
      <div className="field">
        <label htmlFor={`${id}-source`}>
          {kind === 'local' ? 'Path on the server' : 'Repository (owner/name)'}
        </label>
        <input
          id={`${id}-source`}
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder={kind === 'local' ? '/srv/repos/my-project' : 'octo-org/service'}
          aria-describedby={`${id}-source-hint`}
          autoComplete="off"
          spellCheck={false}
        />
        <p id={`${id}-source-hint`} className="hint">
          {kind === 'local'
            ? roots.length
              ? `Must be under an authorised root: ${roots.join(', ')}`
              : 'No local roots are authorised on this server (MODERNISATION_ALLOWED_LOCAL_ROOTS).'
            : allowedGithub.length
              ? `Authorised owners/repositories: ${allowedGithub.join(', ')}`
              : 'No GitHub repositories are authorised on this server (MODERNISATION_ALLOWED_GITHUB_REPOSITORIES).'}
        </p>
      </div>
      <div className="field">
        <label htmlFor={`${id}-name`}>
          Name <span className="optional">(optional)</span>
        </label>
        <input
          id={`${id}-name`}
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-describedby={`${id}-name-hint`}
          autoComplete="off"
        />
        <p id={`${id}-name-hint`} className="hint">
          Defaults to the directory name (local) or owner__repo (GitHub).
        </p>
      </div>
      <ErrorNotice error={register.error} />
      <button type="submit" className="primary" disabled={register.isPending}>
        {register.isPending ? 'Registering…' : 'Register repository'}
      </button>
    </form>
  );
}
