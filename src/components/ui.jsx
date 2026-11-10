import { createContext, useCallback, useContext, useEffect, useState } from 'react'

export {
  DISCLAIMER, FAMILIES, GITHUB_URL, MAX_SCORE, MIN_SCORE, POAM_CITATION, THRESHOLD, cmmcId, listWords, plural,
} from '../lib.js'

// -- status vocabulary: every status has a text label, a tone and a glyph -------------------

export const REQ_STATUS = {
  met: { label: 'Met', tone: 'good', glyph: '✓' },
  not_met: { label: 'Not met', tone: 'bad', glyph: '✕' },
  na: { label: 'Not applicable', tone: 'neutral', glyph: '–' },
  not_assessed: { label: 'Not assessed', tone: 'warn', glyph: '?' },
}

export const ANSWERS = {
  met: { label: 'Met', tone: 'good', glyph: '✓' },
  not_met: { label: 'Not met', tone: 'bad', glyph: '✕' },
  na: { label: 'Not applicable', tone: 'neutral', glyph: '–' },
  unanswered: { label: 'Unanswered', tone: 'outline', glyph: '○' },
}

export const FINDING_RESULTS = {
  met: { label: 'Evidence: met', tone: 'good', glyph: '✓' },
  not_met: { label: 'Evidence: not met', tone: 'bad', glyph: '✕' },
  not_assessed: { label: 'Not assessed by collector', tone: 'neutral', glyph: '–' },
}

export const STATUS_OPTIONS = [
  ['not_met', 'Not met'],
  ['not_assessed', 'Not assessed'],
  ['met', 'Met'],
  ['na', 'Not applicable'],
]

/** Partial-credit choices (DoD Assessment Methodology 5(e)). `null` is the full deduction. */
export const PARTIAL_LABELS = {
  '3.5.3': {
    null: 'MFA not implemented for any users',
    mfa_remote_privileged_only: 'MFA for remote and privileged access only',
  },
  '3.13.11': {
    null: 'Encryption not used',
    encryption_not_fips: 'Encryption used, but not FIPS-validated',
  },
}

export function partialLabel(reqId, choice) {
  const labels = PARTIAL_LABELS[reqId] || {}
  return labels[choice ?? 'null'] || (choice ? choice.replaceAll('_', ' ') : 'Full deduction')
}

// -- small presentational pieces ------------------------------------------------------------

/** Status chip: glyph + text label + tone, so it never relies on color alone. */
export function Chip({ tone = 'neutral', glyph, children, title }) {
  return (
    <span className={`chip ${tone}`} title={title}>
      {glyph && <span className="chip-glyph" aria-hidden="true">{glyph}</span>}
      {children}
    </span>
  )
}

export function StatusChip({ status, map = REQ_STATUS }) {
  const s = map[status] || { label: status, tone: 'neutral' }
  return <Chip tone={s.tone} glyph={s.glyph}>{s.label}</Chip>
}

export function Loading({ label = 'Loading…' }) {
  return (
    <div className="state" role="status">
      <span className="spinner" aria-hidden="true" /> {label}
    </div>
  )
}

export function ErrorState({ error, onRetry }) {
  return (
    <div className="state error" role="alert">
      <strong>Something went wrong.</strong> {error?.message || String(error)}
      {onRetry && <> <button type="button" className="link" onClick={onRetry}>Try again</button></>}
    </div>
  )
}

export function Empty({ children }) {
  return <div className="state">{children}</div>
}

export function Icon({ name, size = 16, label }) {
  const paths = {
    evidence: <><path d="M4 3h6l4 4v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z" /><path d="M10 3v4h4" /><path d="m6 12 2 2 3.5-4" /></>,
    conflict: <><path d="M9.1 2.6 1.7 15.2A1.2 1.2 0 0 0 2.7 17h14.6a1.2 1.2 0 0 0 1-1.8L10.9 2.6a1 1 0 0 0-1.8 0Z" /><path d="M10 7.5v4" /><path d="M10 14.2v.1" /></>,
    github: <path d="M10 1.5a8.5 8.5 0 0 0-2.7 16.6c.4 0 .6-.2.6-.4v-1.5c-2.4.5-2.9-1-2.9-1-.4-1-1-1.3-1-1.3-.8-.5 0-.5 0-.5.9 0 1.3.9 1.3.9.8 1.3 2 1 2.5.7 0-.6.3-1 .6-1.2-1.9-.2-3.9-1-3.9-4.2 0-.9.3-1.7.9-2.3-.1-.2-.4-1.1.1-2.3 0 0 .7-.2 2.3.9a8 8 0 0 1 4.2 0c1.6-1.1 2.3-.9 2.3-.9.5 1.2.2 2 .1 2.3.5.6.9 1.4.9 2.3 0 3.3-2 4-3.9 4.2.3.3.6.8.6 1.6v2.4c0 .2.2.5.6.4A8.5 8.5 0 0 0 10 1.5Z" fill="currentColor" stroke="none" />,
    back: <path d="M12.5 4.5 7 10l5.5 5.5" />,
    arrow: <><path d="M4 10h11" /><path d="m11 5.5 4.5 4.5-4.5 4.5" /></>,
    lock: <><rect x="4" y="9" width="12" height="8.5" rx="1.5" /><path d="M7 9V6.5a3 3 0 0 1 6 0V9" /></>,
    external: <><path d="M11 3.5h5.5V9" /><path d="M16.5 3.5 9 11" /><path d="M14 12v4a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h4" /></>,
    shield: <><path d="M10 1.8 3 4.6v5c0 4.4 3 8 7 8.9 4-.9 7-4.5 7-8.9v-5L10 1.8Z" /><path d="m7 10 2.2 2.2L13.3 8" /></>,
  }
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor"
      strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"
      aria-hidden={label ? undefined : 'true'} role={label ? 'img' : undefined} aria-label={label}
      focusable="false">
      {paths[name]}
    </svg>
  )
}

/** Placeholder for sections that ship in the next release (keeps the navigation from 404ing). */
export function ComingSoon({ title, children }) {
  usePageTitle(title)
  return (
    <div className="page">
      <header className="page-head">
        <h1 tabIndex={-1}>{title}</h1>
      </header>
      <div className="card coming-soon">
        <p className="eyebrow">Coming in this release</p>
        <p>{children}</p>
      </div>
    </div>
  )
}

// -- formatting -----------------------------------------------------------------------------

/** Dates are shown in UTC, which is how the API stores them. */
export function formatDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' })
}

// -- session and data hooks -----------------------------------------------------------------

export const SessionContext = createContext(null)

/** { user, guest, demo, version, authConfigured, assessmentId, assessments, setAssessmentId, signIn } */
export function useSession() {
  return useContext(SessionContext)
}

export function usePageTitle(title) {
  useEffect(() => {
    document.title = title ? `${title} · CMMC Ready` : 'CMMC Ready'
  }, [title])
}

/** Run an async loader whenever deps change. Ignores stale responses. */
export function useAsync(loader, deps) {
  const [state, setState] = useState({ loading: true, error: null, data: null })
  const [tick, setTick] = useState(0)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const load = useCallback(loader, deps)
  useEffect(() => {
    let live = true
    setState((s) => ({ ...s, loading: true, error: null }))
    load()
      .then((data) => live && setState({ loading: false, error: null, data }))
      .catch((error) => live && setState({ loading: false, error, data: null }))
    return () => { live = false }
  }, [load, tick])
  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { ...state, reload, setData: (data) => setState((s) => ({ ...s, data })) }
}
