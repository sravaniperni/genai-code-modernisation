import { PassFail } from '../../components/Badge';
import { JsonDetails, KeyValueList, type KeyValueItem } from '../../components/KeyValue';
import type { JsonObject } from '../../lib/types';

function list(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map((v) => (typeof v === 'string' ? v : JSON.stringify(v)))
    : [];
}

function Paths({ items, empty }: { items: string[]; empty: string }) {
  if (items.length === 0) return <span className="muted">{empty}</span>;
  return (
    <ul className="plain-list">
      {items.map((p) => (
        <li key={p}>
          <code>{p}</code>
        </li>
      ))}
    </ul>
  );
}

/** task.result: the independent verification verdict written by the workflow (and publication info). */
export function VerificationSummary({ result }: { result: JsonObject | null }) {
  if (!result) {
    return <p className="empty">No verification result has been recorded for this task.</p>;
  }
  const items: KeyValueItem[] = [];
  if (typeof result.verified === 'boolean') {
    items.push([
      'Independent verification',
      <PassFail
        key="v"
        passed={result.verified}
        label={result.verified ? 'verified' : 'not verified'}
      />,
    ]);
  }
  if (typeof result.strategy === 'string') items.push(['Strategy', result.strategy]);
  if (typeof result.reason === 'string') items.push(['Reason', result.reason]);
  if (typeof result.attempt_no === 'number')
    items.push(['Accepted attempt', String(result.attempt_no)]);
  if ('files_changed' in result) {
    items.push([
      'Files changed',
      <Paths key="f" items={list(result.files_changed)} empty="none" />,
    ]);
  }
  if ('fixed_tests' in result) {
    items.push(['Tests fixed', <Paths key="t" items={list(result.fixed_tests)} empty="none" />]);
  }
  if ('still_failing_from_baseline' in result) {
    items.push([
      'Still failing (also failing before the change)',
      <Paths key="s" items={list(result.still_failing_from_baseline)} empty="none" />,
    ]);
  }
  if ('unplanned_files' in result) {
    items.push([
      'Files changed outside the plan',
      <Paths key="u" items={list(result.unplanned_files)} empty="none" />,
    ]);
  }
  const verification =
    typeof result.verification === 'object' && result.verification !== null
      ? (result.verification as JsonObject)
      : null;
  if (verification) {
    items.push([
      'Verification checks',
      <ul key="c" className="plain-list">
        {Object.entries(verification).map(([name, passed]) => (
          <li key={name}>
            {name}: <PassFail passed={typeof passed === 'boolean' ? passed : null} />
          </li>
        ))}
      </ul>,
    ]);
  }
  if (typeof result.merged === 'boolean')
    items.push(['Pull request merged', result.merged ? 'yes' : 'no']);
  return (
    <div>
      {items.length ? <KeyValueList items={items} /> : null}
      <JsonDetails label="Raw result JSON" value={result} />
    </div>
  );
}
