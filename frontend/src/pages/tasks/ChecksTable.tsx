import { PassFail } from '../../components/Badge';
import { formatDurationMs } from '../../lib/format';
import type { CheckRun } from '../../lib/types';

/** The check's own verdict when recorded (summary.passed), else exit code 0 without timeout. */
export function checkPassed(check: CheckRun): boolean {
  if (typeof check.summary?.passed === 'boolean') return check.summary.passed;
  return check.exit_code === 0 && !check.timed_out;
}

export function ChecksTable({ checks, caption }: { checks: CheckRun[]; caption: string }) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            <th scope="col" className="num">
              Attempt
            </th>
            <th scope="col">Phase</th>
            <th scope="col">Check</th>
            <th scope="col">Result</th>
            <th scope="col" className="num">
              Exit code
            </th>
            <th scope="col">Duration</th>
            <th scope="col">Details</th>
          </tr>
        </thead>
        <tbody>
          {checks.map((c) => {
            const { passed: _passed, ...summary } = c.summary;
            return (
              <tr key={c.id}>
                <td className="num">{c.attempt_no ?? '—'}</td>
                <td>{c.phase}</td>
                <td>{c.name}</td>
                <td>
                  <PassFail passed={checkPassed(c)} />
                  {c.timed_out ? <div className="cell-note">timed out</div> : null}
                </td>
                <td className="num">{c.exit_code ?? '—'}</td>
                <td>{formatDurationMs(c.duration_ms)}</td>
                <td>
                  <details>
                    <summary>Command and output</summary>
                    <p>
                      <code>{c.command.join(' ')}</code>
                    </p>
                    {Object.keys(summary).length ? (
                      <pre className="code-block small">{JSON.stringify(summary, null, 2)}</pre>
                    ) : null}
                    {c.stdout_tail ? (
                      <>
                        <p className="small muted">stdout (tail)</p>
                        <pre className="code-block small">{c.stdout_tail}</pre>
                      </>
                    ) : null}
                    {c.stderr_tail ? (
                      <>
                        <p className="small muted">stderr (tail)</p>
                        <pre className="code-block small">{c.stderr_tail}</pre>
                      </>
                    ) : null}
                  </details>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
