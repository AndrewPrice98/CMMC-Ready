import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { chartPoints, scoreTicks } from '../history.js'
import { MAX_SCORE, MIN_SCORE, THRESHOLD, plural } from '../lib.js'
import { scoreTone } from '../verdict.js'

// Hand-drawn SVG charts. No chart library: the shapes are simple and this keeps the
// bundle small and the CSP strict.

/** Position of a score on the true scale, -203 to 110, as a percentage of the meter. */
const pct = (value) => ((Math.min(MAX_SCORE, Math.max(MIN_SCORE, value)) - MIN_SCORE) / (MAX_SCORE - MIN_SCORE)) * 100

/**
 * SPRS score as a large numeral over a thin linear meter on the true scale, -203 to 110, with
 * the 88-point conditional threshold marked by a tick. The scale is linear, so most of it is
 * below zero.
 */
export function ScoreGauge({ score, provisional }) {
  const tone = scoreTone(score)
  const label = `SPRS score ${score} on a scale from ${MIN_SCORE} to ${MAX_SCORE}. `
    + `Conditional Level 2 status needs at least ${THRESHOLD}.${provisional ? ' The score is provisional.' : ''}`
  return (
    <figure className="score-meter">
      <p className="score-value num">
        <span>{score < 0 ? `−${Math.abs(score)}` : score}</span>
        <span className="score-of">of {MAX_SCORE}</span>
      </p>
      <div className="meter" role="img" aria-label={label}>
        <div className="meter-track">
          <div className="meter-zone" style={{ left: `${pct(THRESHOLD)}%`, width: `${100 - pct(THRESHOLD)}%` }} />
          <div className={`meter-fill ${tone}`} style={{ width: `${pct(score)}%` }} />
          <div className="meter-tick" style={{ left: `${pct(0)}%` }} />
          <div className="meter-tick strong" style={{ left: `${pct(THRESHOLD)}%` }} />
        </div>
        <div className="meter-scale" aria-hidden="true">
          <span style={{ left: '0%' }}>{'−'}203</span>
          <span style={{ left: `${pct(0)}%` }}>0</span>
          <span className="strong" style={{ left: `${pct(THRESHOLD)}%` }}>{THRESHOLD}</span>
        </div>
      </div>
      <figcaption className="meter-note">
        Tick at {THRESHOLD}: the threshold for conditional Level 2 status. {THRESHOLD}–{MAX_SCORE} is shaded.
      </figcaption>
    </figure>
  )
}

const CELL = 10
const GAP = 3
const ORDER = ['not_met', 'not_assessed', 'met', 'na']

function Cell({ status, x }) {
  const y = 0.5
  const s = CELL - 1
  if (status === 'not_met') {
    return (
      <g className="cell not_met">
        <rect x={x + 0.5} y={y} width={s} height={s} rx="2" />
        <path d={`M${x + 3},${y + 3} l3,3 M${x + 6},${y + 3} l-3,3`} />
      </g>
    )
  }
  if (status === 'na') {
    return (
      <g className="cell na">
        <rect x={x + 0.5} y={y} width={s} height={s} rx="2" />
        <path d={`M${x + 2.5},${y + 4.5} h4`} />
      </g>
    )
  }
  return <rect className={`cell ${status}`} x={x + 0.5} y={y} width={s} height={s} rx="2" />
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
  const height = narrow ? 220 : 240
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
          const anchor = points.length > 1 && i === 0 ? 'start' : points.length > 1 && i === points.length - 1 ? 'end' : 'middle'
          const dx = anchor === 'start' ? -6 : anchor === 'end' ? 6 : 0
          return (
            <g key={p.id} className="hc-point">
              <circle cx={p.x} cy={p.y} r="4" className={p.provisional ? 'hollow' : ''} />
              <text className="hc-value" x={p.x + dx} y={p.y - 12} textAnchor={anchor}>{fmtScore(p.score)}</text>
              <text className="hc-date" x={p.x + dx} y={box.bottom + 22} textAnchor={anchor}>{formatDate(p.date)}</text>
            </g>
          )
        })}
      </svg>
      <figcaption className="chart-note">
        Shaded band: {THRESHOLD}–{MAX_SCORE}, the conditional status range. Hollow point: provisional score.
      </figcaption>
    </figure>
  )
}
