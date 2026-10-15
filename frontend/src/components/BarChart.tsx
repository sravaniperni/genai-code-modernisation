import { useElementWidth } from '../hooks/useElementWidth';

export interface BarSeries {
  name: string;
  values: (number | null)[];
}

interface BarChartProps {
  /** Accessible name and visible caption. */
  title: string;
  categories: string[];
  series: BarSeries[];
  /** Upper end of the scale; defaults to the largest value. Use 1 for rates. */
  max?: number;
  format?: (value: number) => string;
  formatCategory?: (category: string) => string;
}

const ROW_GAP = 10;
const BAR_SINGLE = 16;
const BAR_GROUPED = 12;
const SERIES_GAP = 2;
const VALUE_SPACE = 64;

/** Horizontal bar with a 4px rounded data end and a square end at the baseline. */
function barPath(x: number, y: number, w: number, h: number): string {
  const r = Math.min(4, w, h / 2);
  return [
    `M${x},${y}`,
    `H${x + w - r}`,
    `Q${x + w},${y} ${x + w},${y + r}`,
    `V${y + h - r}`,
    `Q${x + w},${y + h} ${x + w - r},${y + h}`,
    `H${x}`,
    'Z',
  ].join(' ');
}

/**
 * Small hand-written horizontal bar chart (single series or two series side by side). Values are
 * labelled directly at the bar tip; with more than one series a legend names them.
 */
export function BarChart({
  title,
  categories,
  series,
  max,
  format = (v) => String(v),
  formatCategory = (c) => c,
}: BarChartProps) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const grouped = series.length > 1;
  const barH = grouped ? BAR_GROUPED : BAR_SINGLE;
  const groupH = series.length * barH + (series.length - 1) * SERIES_GAP;
  const rowH = groupH + ROW_GAP;
  const labelW = Math.min(200, Math.max(96, Math.round(width * 0.32)));
  const plotW = Math.max(40, width - labelW - VALUE_SPACE);
  const height = categories.length * rowH + 4;
  const allValues = series.flatMap((s) => s.values).filter((v): v is number => v !== null);
  const scaleMax = max ?? Math.max(1, ...allValues);

  const description = categories
    .map((c, i) =>
      series
        .map((s) => {
          const v = s.values[i];
          const shown = v === null || v === undefined ? 'no data' : format(v);
          return grouped ? `${s.name} ${shown}` : shown;
        })
        .map((text) => `${formatCategory(c)}: ${text}`)
        .join(', '),
    )
    .join('; ');

  return (
    <figure className="chart">
      <figcaption className="chart-title">{title}</figcaption>
      {grouped ? (
        <ul className="chart-legend" aria-label="Legend">
          {series.map((s, i) => (
            <li key={s.name}>
              <span className={`swatch series-${i + 1}`} aria-hidden="true" />
              {s.name}
            </li>
          ))}
        </ul>
      ) : null}
      <div ref={ref} className="chart-body">
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={`${title}. ${description}`}
          className="chart-svg"
        >
          <line
            x1={labelW}
            x2={labelW}
            y1={0}
            y2={height}
            className="chart-axis"
            shapeRendering="crispEdges"
          />
          {categories.map((category, ci) => {
            const top = ci * rowH + ROW_GAP / 2;
            return (
              <g key={category} className="chart-row">
                <text x={labelW - 8} y={top + groupH / 2} className="chart-label" textAnchor="end">
                  {formatCategory(category)}
                </text>
                {series.map((s, si) => {
                  const value = s.values[ci] ?? null;
                  const y = top + si * (barH + SERIES_GAP);
                  const w = value === null ? 0 : Math.max(0, (value / scaleMax) * plotW);
                  const shown = value === null ? 'no data' : format(value);
                  return (
                    <g key={s.name}>
                      <title>{`${formatCategory(category)}${grouped ? ` (${s.name})` : ''}: ${shown}`}</title>
                      {w > 0 ? (
                        <path
                          d={barPath(labelW + 1, y, w, barH)}
                          className={`bar series-${si + 1}`}
                        />
                      ) : null}
                      <rect
                        x={labelW}
                        y={y}
                        width={plotW + VALUE_SPACE}
                        height={barH}
                        className="chart-hit"
                      />
                      <text x={labelW + w + 6} y={y + barH / 2} className="chart-value">
                        {shown}
                      </text>
                    </g>
                  );
                })}
              </g>
            );
          })}
        </svg>
      </div>
    </figure>
  );
}
