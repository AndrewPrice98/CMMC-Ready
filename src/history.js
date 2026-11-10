// Score history: chart geometry and the change summary. Pure functions for Node's test runner.
import { MAX_SCORE } from './lib.js'

/**
 * The vertical range of the score chart. The top is always the maximum (110) so the
 * 88-point threshold sits in the same place on every chart; the bottom is 0, or a round
 * number below the lowest score when a score is negative.
 */
export function scoreRange(scores) {
  const lowest = Math.min(0, ...scores)
  const bottom = lowest < 0 ? Math.floor((lowest - 5) / 25) * 25 : 0
  return { min: bottom, max: MAX_SCORE }
}

/** Ticks for the vertical axis: the maximum, 0 and the bottom of the range (88 is drawn separately). */
export function scoreTicks(range) {
  return [...new Set([range.max, 0, range.min])].filter((t) => t >= range.min && t <= range.max)
    .sort((a, b) => b - a)
}

/**
 * Point positions inside a box. Assessments are spaced evenly in date order; a single
 * assessment sits in the middle.
 */
export function chartPoints(assessments, box) {
  const range = scoreRange(assessments.map((a) => a.score))
  const { left, right, top, bottom } = box
  const y = (score) => top + ((range.max - score) / (range.max - range.min)) * (bottom - top)
  const n = assessments.length
  const x = (i) => (n === 1 ? (left + right) / 2 : left + (i / (n - 1)) * (right - left))
  return {
    range,
    y,
    points: assessments.map((a, i) => ({ ...a, x: x(i), y: y(a.score) })),
  }
}

export const CHANGE_KINDS = [
  ['became_met', 'Became met', 'good'],
  ['regressed', 'Regressions', 'bad'],
  ['became_na', 'Became not applicable', 'neutral'],
  ['no_longer_na', 'No longer not applicable', 'warn'],
]

/** One row per pair of consecutive assessments, with titles and the score change. */
export function changeRows(history) {
  const byId = Object.fromEntries(history.assessments.map((a) => [a.id, a]))
  return history.changes.map((c) => {
    const from = byId[c.from_id]
    const to = byId[c.to_id]
    const total = CHANGE_KINDS.reduce((n, [key]) => n + (c[key]?.length || 0), 0)
    return { ...c, from, to, delta: from && to ? to.score - from.score : null, total }
  })
}

/** "+45", "−3", "0" with a real minus sign. */
export function signed(n) {
  if (n > 0) return `+${n}`
  if (n < 0) return `−${Math.abs(n)}`
  return '0'
}
