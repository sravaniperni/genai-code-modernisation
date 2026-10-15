import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';
import { HEALTH_REFRESH_MS } from '../lib/config';

/** Live backend status from GET /api/health, shown in the header on every screen. */
export function HealthIndicator() {
  const health = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: HEALTH_REFRESH_MS,
  });

  if (health.isPending) {
    return (
      <p className="health" role="status">
        Checking API…
      </p>
    );
  }
  if (health.isError) {
    return (
      <p className="health" role="status">
        <span className="dot dot-danger" aria-hidden="true" /> API unreachable
      </p>
    );
  }
  const h = health.data;
  return (
    <ul className="health" aria-label="Backend status">
      <li>
        <span className={`dot ${h.status === 'ok' ? 'dot-ok' : 'dot-danger'}`} aria-hidden="true" />
        API {h.status}
      </li>
      <li>
        <span className={`dot ${h.database ? 'dot-ok' : 'dot-danger'}`} aria-hidden="true" />
        Database {h.database ? 'reachable' : 'unreachable'}
      </li>
      <li>
        <span className={`dot ${h.model_configured ? 'dot-ok' : 'dot-off'}`} aria-hidden="true" />
        Model {h.model_configured ? 'configured' : 'not configured'}
      </li>
      <li>
        <span className={`dot ${h.github_configured ? 'dot-ok' : 'dot-off'}`} aria-hidden="true" />
        GitHub {h.github_configured ? 'configured' : 'not configured'}
      </li>
    </ul>
  );
}
