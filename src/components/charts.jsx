import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { chartPoints, scoreTicks } from '../history.js'
import { MAX_SCORE, MIN_SCORE, THRESHOLD, plural } from '../lib.js'
import { scoreTone } from '../verdict.js'

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

/** Width of an element, kept current with a ResizeObserver, so SVG text stays at its real size. */
export function useWidth(ref, fallback = 640) {
  const [width, setWidth] = useState(fallback)
  useEffect(() => {
    const el = ref.current
    if (!el) return undefined
    const measure = () => setWidth(Math.max(240, Math.round(el.getBoundingClientRect().width)))
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [ref])
  return width
}

const fmtScore = (n) => (n < 0 ? `−${Math.abs(n)}` : String(n))

/**
 * SPRS score over assessments, oldest first, with the 88-point threshold and the
 * conditional-status zone (88-110) marked. Provisional scores are hollow points.
 */
export function ScoreHistoryChart({ assessments, formatDate }) {
  const wrap = useRef(null)
  const width = useWidth(wrap)
  const narrow = width < 480
  const height = narrow ? 240 : 280
  const box = { left: narrow ? 40 : 48, right: width - (narrow ? 28 : 44), top: 28, bottom: height - 48 }
  const { range, y, points } = chartPoints(assessments, box)
  const ticks = scoreTicks(range)
  const label = `SPRS score over ${plural(assessments.length, 'assessment')}: `
    + assessments.map((a) => `${formatDate(a.date)}, ${fmtScore(a.score)}${a.provisional ? ' (provisional)' : ''}`).join('; ')
    + `. Conditional Level 2 status needs at least ${THRESHOLD}.`
  return (
    <figure className="history-chart" ref={wrap}>
      <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label}>
        <rect className="hc-zone" x={box.left} y={y(MAX_SCORE)} width={box.right - box.left} height={y(THRESHOLD) - y(MAX_SCORE)} />
        {ticks.map((t) => (
          <g key={t} className="hc-tick">
            <line x1={box.left} x2={box.right} y1={y(t)} y2={y(t)} />
            <text x={box.left - 8} y={y(t) + 4} textAnchor="end">{fmtScore(t)}</text>
          </g>
        ))}
        <g className="hc-threshold">
          <line x1={box.left} x2={box.right} y1={y(THRESHOLD)} y2={y(THRESHOLD)} />
          <text x={box.left - 8} y={y(THRESHOLD) + 4} textAnchor="end">{THRESHOLD}</text>
          <text className="hc-threshold-label" x={box.left + 8} y={y(THRESHOLD) + 15}>
            {narrow ? 'Conditional status' : `${THRESHOLD}: conditional Level 2 status`}
          </text>
        </g>
        {points.length > 1 && (
          <polyline className="hc-line" pathLength="1" points={points.map((p) => `${p.x},${p.y}`).join(' ')} />
        )}
        {points.map((p, i) => {
          const tone = scoreTone(p.score)
          const anchor = points.length > 1 && i === 0 ? 'start' : points.length > 1 && i === points.length - 1 ? 'end' : 'middle'
          const dx = anchor === 'start' ? -6 : anchor === 'end' ? 6 : 0
          return (
            <g key={p.id} className="hc-point">
              <circle cx={p.x} cy={p.y} r="6" className={`${tone} ${p.provisional ? 'hollow' : ''}`} />
              <text className={`hc-value ${tone}`} x={p.x + dx} y={p.y - 13} textAnchor={anchor}>{fmtScore(p.score)}</text>
              <text className="hc-date" x={p.x + dx} y={box.bottom + 22} textAnchor={anchor}>{formatDate(p.date)}</text>
            </g>
          )
        })}
      </svg>
      <figcaption className="gauge-legend">
        <span><i className="swatch line" aria-hidden="true" /> SPRS score</span>
        <span><i className="swatch zone" aria-hidden="true" /> {THRESHOLD}–{MAX_SCORE}: conditional status range</span>
        <span><i className="swatch hollow" aria-hidden="true" /> Hollow point: provisional</span>
      </figcaption>
    </figure>
  )
}
