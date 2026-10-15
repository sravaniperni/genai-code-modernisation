import { Link, Outlet, useLocation } from 'react-router';
import { HealthIndicator } from './HealthIndicator';

const NAV: { to: string; label: string; match: (path: string) => boolean }[] = [
  { to: '/', label: 'Dashboard', match: (p) => p === '/' },
  { to: '/repositories', label: 'Repositories', match: (p) => p.startsWith('/repositories') },
  { to: '/tasks/new', label: 'New task', match: (p) => p === '/tasks/new' },
  { to: '/tasks', label: 'Tasks', match: (p) => p.startsWith('/tasks') && p !== '/tasks/new' },
  { to: '/evaluation', label: 'Evaluation', match: (p) => p.startsWith('/evaluation') },
  { to: '/settings', label: 'Settings', match: (p) => p.startsWith('/settings') },
];

export function Layout() {
  const { pathname } = useLocation();
  return (
    <div className="app">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <Link to="/" className="brand">
          <span className="brand-mark" aria-hidden="true" />
          Modernisation Platform
        </Link>
        <HealthIndicator />
      </header>
      <div className="shell">
        <nav aria-label="Primary" className="sidenav">
          <ul>
            {NAV.map((item) => {
              const active = item.match(pathname);
              return (
                <li key={item.to}>
                  <Link
                    to={item.to}
                    aria-current={active ? 'page' : undefined}
                    className={active ? 'active' : undefined}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <main id="main" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
