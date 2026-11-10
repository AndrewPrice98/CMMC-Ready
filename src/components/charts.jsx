import { Link } from 'react-router-dom'
import { MAX_SCORE, MIN_SCORE, THRESHOLD, plural } from './ui.jsx'

// Hand-drawn SVG charts. No chart library: the shapes are simple and this keeps the
// bundle small and the CSP strict.

const GAUGE = { w: 360, h: 206, cx: 180, cy: 170, r: 132, stroke: 20 }

function gaugePoint(value, radius = GAUGE.r) {
  const t = (Math.min(MAX_SCORE, Math.max(MIN_SCORE, value)) - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)
  const angle = Math.PI * (1 - t)
  return [GAUGE.cx + radius * Math.cos(angle), GAUGE.cy - radius * Math.sin(angle)]
}

function arcPath(from, to) {
  const [x1, y1] = gaugePoint(from)
  const [x2, y2] = gaugePoint(to)
  return `M${x1.toFixed(2)},${y1.toFixed(2)} A${GAUGE.r},${GAUGE.r} 0 0 1 ${x2.toFixed(2)},${y2.toFixed(2)}`
}

export function scoreTone(score) {
  if (score >= THRESHOLD) return 'good'
  if (score >= 0) return 'warn'
  return 'bad'
}

function Tick({ value, label, emphasis }) {
  const [xi, yi] = gaugePoint(value, GAUGE.r - GAUGE.stroke / 2 - 5)
  const [xo, yo] = gaugePoint(value, GAUGE.r + GAUGE.stroke / 2 + 5)
  const [xl, yl] = gaugePoint(value, GAUGE.r + GAUGE.stroke / 2 + 17)
  return (
    <g className={emphasis ? 'gauge-tick strong' : 'gauge-tick'}>
      <line x1={xi} y1={yi} x2={xo} y2={yo} />
      <text x={xl} y={yl + 4} textAnchor={value > 40 ? 'start' : value < -40 ? 'end' : 'middle'}>{label}</text>
    </g>
  )
}

/**
 * SPRS score gauge on the true scale, -203 to 110, with the 88-point conditional
 * threshold marked. The scale is linear, so most of the arc is below zero.
 */
export function ScoreGauge({ score, provisional }) {
  const tone = scoreTone(score)
  const { w, h, cx, cy } = GAUGE
  return (
    <figure className="gauge">
      <svg viewBox={`0 0 ${w} ${h}`} role="img"
        aria-label={`SPRS score ${score} on a scale from ${MIN_SCORE} to ${MAX_SCORE}. `
          + `Conditional Level 2 status needs at least ${THRESHOLD}.${provisional ? ' The score is provisional.' : ''}`}>
        <path className="gauge-track" d={arcPath(MIN_SCORE, MAX_SCORE)} strokeWidth={GAUGE.stroke} />
        <path className="gauge-zone" d={arcPath(THRESHOLD, MAX_SCORE)} strokeWidth={GAUGE.stroke} />
        <path className={`gauge-value ${tone}`} d={arcPath(MIN_SCORE, score)} strokeWidth={GAUGE.stroke}
          pathLength="1" />
        <Tick value={0} label="0" />
        <Tick value={THRESHOLD} label="88" emphasis />
        <text className="gauge-end" x={gaugePoint(MIN_SCORE)[0]} y={cy + 26} textAnchor="middle">−203</text>
        <text className="gauge-end" x={gaugePoint(MAX_SCORE)[0]} y={cy + 26} textAnchor="middle">110</text>
        <text className={`gauge-score ${tone}`} x={cx} y={cy - 22} textAnchor="middle">
          {score < 0 ? `−${Math.abs(score)}` : score}
        </text>
        <text className="gauge-caption" x={cx} y={cy + 4} textAnchor="middle">SPRS score of {MAX_SCORE}</text>
      </svg>
      <figcaption className="gauge-legend">
        <span><i className={`swatch ${tone}`} aria-hidden="true" /> Current score</span>
        <span><i className="swatch zone" aria-hidden="true" /> {THRESHOLD}–{MAX_SCORE}: conditional status range</span>
      </figcaption>
    </figure>
  )
}

const CELL = 11
const GAP = 3
const ORDER = ['not_met', 'not_assessed', 'met', 'na']

function Cell({ status, x }) {
  const y = 0.5
  const s = CELL - 1
  if (status === 'not_met') {
    return (
      <g className="cell not_met">
        <rect x={x + 0.5} y={y} width={s} height={s} rx="2.5" />
        <path d={`M${x + 3.5},${y + 3} l4,4 M${x + 7.5},${y + 3} l-4,4`} />
      </g>
    )
  }
  if (status === 'na') {
    return (
      <g className="cell na">
        <rect x={x + 0.5} y={y} width={s} height={s} rx="2.5" />
        <path d={`M${x + 3},${y + 5} h5`} />
      </g>
    )
  }
  return <rect className={`cell ${status}`} x={x + 0.5} y={y} width={s} height={s} rx="2.5" />
}

function FamilyCells({ row }) {
  const cells = ORDER.flatMap((s) => Array.from({ length: row[s] }, () => s))
  const width = cells.length * (CELL + GAP) - GAP + 1
  return (
    <svg className="cells" viewBox={`0 0 ${width} ${CELL + 1}`} width={width} height={CELL + 1}
      aria-hidden="true" focusable="false">
      {cells.map((s, i) => <Cell key={i} status={s} x={i * (CELL + GAP)} />)}
    </svg>
  )
}

export function HeatmapLegend() {
  const items = [['met', 'Met'], ['not_met', 'Not met'], ['not_assessed', 'Not assessed'], ['na', 'Not applicable']]
  return (
    <ul className="heat-legend" aria-label="Legend">
      {items.map(([status, label]) => (
        <li key={status}>
          <svg viewBox={`0 0 ${CELL + 1} ${CELL + 1}`} width={CELL + 1} height={CELL + 1} aria-hidden="true">
            <Cell status={status} x={0} />
          </svg>
          {label}
        </li>
      ))}
    </ul>
  )
}

/** One row per family, one cell per requirement, gaps first. Each row links to the family's requirements. */
export function FamilyHeatmap({ rows }) {
  return (
    <ul className="heatmap">
      {rows.map((row) => {
        const total = row.met + row.not_met + row.na + row.not_assessed
        const done = row.met + row.na
        const summary = `${row.name}: ${done} of ${total} met or not applicable`
          + (row.not_met ? `, ${row.not_met} not met` : '')
          + (row.not_assessed ? `, ${row.not_assessed} not assessed` : '')
          + (row.points_lost ? `, ${plural(row.points_lost, 'point')} lost` : '')
        return (
          <li key={row.family}>
            <Link to={`/requirements?family=${row.family}`} className="heat-row" aria-label={summary}>
              <span className="heat-code">{row.family}</span>
              <span className="heat-name" title={row.name}>{row.name}</span>
              <FamilyCells row={row} />
              <span className="heat-count num">{done}/{total}</span>
              <span className={`heat-points num ${row.points_lost ? 'lost' : ''}`}>
                {row.points_lost ? `−${row.points_lost}` : '0'}
              </span>
            </Link>
          </li>
        )
      })}
    </ul>
  )
}
