import { JsonDetails } from '../../components/KeyValue';
import type { JsonObject } from '../../lib/types';

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
}

interface PlanStep {
  description: string;
  files: string[];
}

function steps(value: unknown): PlanStep[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((s): s is JsonObject => typeof s === 'object' && s !== null)
    .map((s) => ({
      description: typeof s.description === 'string' ? s.description : JSON.stringify(s),
      files: strings(s.files),
    }));
}

/** The plan recorded on the task (agents/prompts.py Plan), with the raw JSON available below. */
export function PlanView({ plan }: { plan: JsonObject | null }) {
  if (!plan) return <p className="empty">No plan has been recorded for this task yet.</p>;
  const targetFiles = strings(plan.target_files);
  const planSteps = steps(plan.steps);
  const risks = strings(plan.risks);
  const validation = strings(plan.validation);
  const questions = strings(plan.clarification_questions);
  return (
    <div className="plan">
      {typeof plan.summary === 'string' ? <p>{plan.summary}</p> : null}
      {typeof plan.strategy === 'string' ? (
        <p className="muted">Strategy: {plan.strategy.replace(/_/g, ' ')}</p>
      ) : null}
      {targetFiles.length ? (
        <>
          <h4>Target files</h4>
          <ul>
            {targetFiles.map((f) => (
              <li key={f}>
                <code>{f}</code>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      {planSteps.length ? (
        <>
          <h4>Steps</h4>
          <ol>
            {planSteps.map((s, i) => (
              <li key={i}>
                {s.description}
                {s.files.length ? (
                  <span className="muted small"> ({s.files.map((f) => f).join(', ')})</span>
                ) : null}
              </li>
            ))}
          </ol>
        </>
      ) : null}
      {risks.length ? (
        <>
          <h4>Risks</h4>
          <ul>
            {risks.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </>
      ) : null}
      {validation.length ? (
        <>
          <h4>Validation</h4>
          <ul>
            {validation.map((v) => (
              <li key={v}>{v}</li>
            ))}
          </ul>
        </>
      ) : null}
      {plan.needs_clarification === true || questions.length ? (
        <div className="notice notice-attention">
          <p className="notice-title">The agent asked for clarification</p>
          <ul>
            {questions.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <JsonDetails label="Raw plan JSON" value={plan} />
    </div>
  );
}
