// POA&M dates and checks. Pure functions, so Node's test runner can import them.
//
// 32 CFR §170.21: a conditional Level 2 status lasts 180 days, so every POA&M item has to
// be closed out within 180 days of the assessment. The server uses the assessment's
// completion date, or its start date while it is in progress; so does this module.

export const CLOSEOUT_DAYS = 180
export const POAM_STATUSES = ['open', 'in_progress', 'closed']

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

/** True for a real calendar date written YYYY-MM-DD. */
export function isIsoDate(value) {
  if (typeof value !== 'string' || !ISO_DATE.test(value)) return false
  const d = new Date(`${value}T00:00:00Z`)
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === value
}

/** "2026-10-12T13:00:00Z" + 180 -> "2027-04-10" (calendar days, UTC). */
export function addDays(iso, days) {
  const d = new Date(`${String(iso).slice(0, 10)}T00:00:00Z`)
  if (Number.isNaN(d.getTime())) return null
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

/** The date the POA&M closeout window runs from. */
export function assessmentDate(assessment) {
  const when = assessment?.completed_at || assessment?.started_at
  return when ? when.slice(0, 10) : null
}

/** The last day a POA&M item may be closed out. */
export function closeoutDeadline(assessment) {
  const start = assessmentDate(assessment)
  return start ? addDays(start, CLOSEOUT_DAYS) : null
}

/** Today's date in UTC, as YYYY-MM-DD (dates are stored and shown in UTC). */
export function todayIso(now = new Date()) {
  return now.toISOString().slice(0, 10)
}

/** Whole days from `from` to `to` (both YYYY-MM-DD); negative when `to` is earlier. */
export function daysBetween(from, to) {
  const a = Date.parse(`${from}T00:00:00Z`)
  const b = Date.parse(`${to}T00:00:00Z`)
  return Math.round((b - a) / 86_400_000)
}

/**
 * Flags for one item's due date.
 * - overdue: not closed and the due date has passed.
 * - beyondCloseout: not closed and due after the 180-day closeout deadline.
 * - noDueDate: not closed and no due date at all.
 */
export function dueFlags(item, deadline, today) {
  const open = item.status !== 'closed'
  const due = item.due_date || null
  return {
    overdue: Boolean(open && due && due < today),
    beyondCloseout: Boolean(open && due && deadline && due > deadline),
    noDueDate: Boolean(open && !due),
    daysLeft: open && due ? daysBetween(today, due) : null,
  }
}

/** Counts for the summary tiles. */
export function poamSummary(items, deadline, today) {
  const out = { total: items.length, open: 0, in_progress: 0, closed: 0, overdue: 0, beyondCloseout: 0 }
  for (const item of items) {
    if (item.status in out) out[item.status] += 1
    const flags = dueFlags(item, deadline, today)
    if (flags.overdue) out.overdue += 1
    if (flags.beyondCloseout) out.beyondCloseout += 1
  }
  return out
}

export function milestoneProgress(milestones = []) {
  return { done: milestones.filter((m) => m.done).length, total: milestones.length }
}

/** Requirement IDs sort numerically: 3.1.3 before 3.1.21 before 3.13.1. */
export function compareReqIds(a, b) {
  const pa = a.split('.').map(Number)
  const pb = b.split('.').map(Number)
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0)
    if (d) return d
  }
  return 0
}

/**
 * Gaps that have no POA&M item yet, from the server's drafts: the ones the rule allows
 * (an admin may add them) and the ones it does not (with the reason).
 */
export function openGaps(drafts, items) {
  const have = new Set(items.map((i) => i.req_id))
  const missing = drafts.filter((d) => !have.has(d.req_id)).sort((a, b) => compareReqIds(a.req_id, b.req_id))
  return { eligible: missing.filter((d) => d.allowed), notAllowed: missing.filter((d) => !d.allowed) }
}

/** Client-side checks before a save; the server checks again. Returns an error or null. */
export function validatePoamForm(form) {
  if (!form.weakness?.trim()) return 'Describe the weakness.'
  if (form.due_date && !isIsoDate(form.due_date)) return 'The due date must be a real date (YYYY-MM-DD).'
  if (!POAM_STATUSES.includes(form.status)) return 'Choose a status.'
  for (const [i, m] of (form.milestones || []).entries()) {
    if (!m.description?.trim()) return `Milestone ${i + 1} needs a description.`
    if (m.due && !isIsoDate(m.due)) return `Milestone ${i + 1} has an invalid date.`
  }
  return null
}

/** The request body for POST/PATCH from the editor form. */
export function poamBody(form) {
  return {
    weakness: form.weakness.trim(),
    remediation: form.remediation.trim(),
    owner: form.owner.trim(),
    due_date: form.due_date || null,
    status: form.status,
    milestones: form.milestones.map((m) => ({
      description: m.description.trim(), due: m.due || null, done: Boolean(m.done),
    })),
  }
}
