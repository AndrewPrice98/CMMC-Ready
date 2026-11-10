import { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from 'react'
import {
  ArrowLeft, ArrowRight, Calendar, Check, ChevronDown, CircleDashed, CirclePlus, Cloud, Copy, Download, ExternalLink,
  FileCheck, FileText, Info, Layers, LayoutDashboard, ListChecks, Lock, Menu, Pencil, Plus, ScrollText, Search,
  Terminal, Trash2, TriangleAlert, Upload, X, ClipboardList, History as HistoryIcon, Circle, CircleCheck, Monitor,
} from 'lucide-react'

export {
  ASSET_CATEGORIES, COLLECTORS, DISCLAIMER, FAMILIES, GITHUB_URL, MAX_SCORE, MIN_SCORE, POAM_CITATION, THRESHOLD,
  cmmcId, listWords, plural,
} from '../lib.js'

// -- status vocabulary: every status has a text label and a tone -------------------

export const REQ_STATUS = {
  met: { label: 'Met', tone: 'good' },
  not_met: { label: 'Not met', tone: 'bad' },
  na: { label: 'Not applicable', tone: 'neutral' },
  not_assessed: { label: 'Not assessed', tone: 'warn' },
}

export const ANSWERS = {
  met: { label: 'Met', tone: 'good' },
  not_met: { label: 'Not met', tone: 'bad' },
  na: { label: 'Not applicable', tone: 'neutral' },
  unanswered: { label: 'Unanswered', tone: 'outline' },
}

export const FINDING_RESULTS = {
  met: { label: 'Evidence: met', tone: 'good' },
  not_met: { label: 'Evidence: not met', tone: 'bad' },
  not_assessed: { label: 'Not assessed by collector', tone: 'neutral' },
}

export const POAM_STATUS = {
  open: { label: 'Open', tone: 'warn' },
  in_progress: { label: 'In progress', tone: 'info' },
  closed: { label: 'Closed', tone: 'good' },
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

/**
 * The CMMC Ready mark: a ring of 14 arc segments, one per control family. Eleven are filled and
 * three are open. It takes the accent colour from the theme.
 */
const RING_FILLED = 'M16.52 1.01A15 15 0 0 1 22.03 2.27L19.62 7.76A9 9 0 0 0 16.31 7.01ZM22.98 2.72A15 15 0 0 1 27.39 6.24L22.84 10.15A9 9 0 0 0 20.19 8.03ZM28.05 7.06A15 15 0 0 1 30.50 12.15L24.70 13.69A9 9 0 0 0 23.23 10.64ZM30.50 19.85A15 15 0 0 1 28.05 24.94L23.23 21.36A9 9 0 0 0 24.70 18.31ZM27.39 25.76A15 15 0 0 1 22.98 29.28L20.19 23.97A9 9 0 0 0 22.84 21.85ZM22.03 29.73A15 15 0 0 1 16.52 30.99L16.31 24.99A9 9 0 0 0 19.62 24.24ZM15.48 30.99A15 15 0 0 1 9.97 29.73L12.38 24.24A9 9 0 0 0 15.69 24.99ZM3.95 24.94A15 15 0 0 1 1.50 19.85L7.30 18.31A9 9 0 0 0 8.77 21.36ZM1.27 18.83A15 15 0 0 1 1.27 13.17L7.16 14.30A9 9 0 0 0 7.16 17.70ZM4.61 6.24A15 15 0 0 1 9.02 2.72L11.81 8.03A9 9 0 0 0 9.16 10.15ZM9.97 2.27A15 15 0 0 1 15.48 1.01L15.69 7.01A9 9 0 0 0 12.38 7.76Z'
const RING_OPEN = 'M30.73 13.17A15 15 0 0 1 30.73 18.83L24.84 17.70A9 9 0 0 0 24.84 14.30ZM9.02 29.28A15 15 0 0 1 4.61 25.76L9.16 21.85A9 9 0 0 0 11.81 23.97ZM1.50 12.15A15 15 0 0 1 3.95 7.06L8.77 10.64A9 9 0 0 0 7.30 13.69Z'

export function LogoMark({ size = 28 }) {
  return (
    <svg className="logo-mark" width={size} height={size} viewBox="0 0 32 32"
      aria-hidden="true" focusable="false">
      <path fill="currentColor" d={RING_FILLED} />
      <path fill="currentColor" fillOpacity="0.22" d={RING_OPEN} />
    </svg>
  )
}

/** Compact tag: tinted background, no icon, no border. Meaning is always in the text. */
export function Chip({ tone = 'neutral', children, title }) {
  return <span className={`tag ${tone}`} title={title}>{children}</span>
}

/** Status as a dot plus text, so it never relies on colour alone. */
export function Status({ status, map = REQ_STATUS }) {
  const s = map[status] || { label: status, tone: 'neutral' }
  return <span className={`status ${s.tone}`}><i className="dot" aria-hidden="true" />{s.label}</span>
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

const ICONS = {
  evidence: FileCheck, conflict: TriangleAlert, back: ArrowLeft, arrow: ArrowRight, lock: Lock, external: ExternalLink,
  copy: Copy, check: Check, download: Download, upload: Upload, plus: Plus, edit: Pencil, trash: Trash2,
  terminal: Terminal, file: FileText, close: X, calendar: Calendar, info: Info, cloud: Cloud, monitor: Monitor,
  menu: Menu, search: Search, chevron: ChevronDown, circle: Circle, 'circle-check': CircleCheck,
  overview: LayoutDashboard, requirements: ListChecks, poam: ClipboardList, documents: FileText, history: HistoryIcon,
  scope: Layers, log: ScrollText, 'circle-dashed': CircleDashed, 'circle-plus': CirclePlus,
}

/** Line icon from lucide-react: 16 px, 1.5 stroke, takes the text colour. */
export function Icon({ name, size = 16, label }) {
  const Glyph = ICONS[name]
  if (!Glyph) return null
  return (
    <Glyph className="icon" size={size} strokeWidth={1.5} absoluteStrokeWidth aria-hidden={label ? undefined : 'true'}
      role={label ? 'img' : undefined} aria-label={label} focusable="false" />
  )
}

export function formatValue(value) {
  if (value === null || value === undefined) return 'none'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/** An observed value: `key = value` pairs for objects, the value itself otherwise. */
export function Observed({ observed }) {
  const entries = observed && typeof observed === 'object' && !Array.isArray(observed)
    ? Object.entries(observed) : null
  if (!entries) return <code>{formatValue(observed)}</code>
  if (!entries.length) return <span className="muted">nothing reported</span>
  return (
    <>
      {entries.map(([k, v], i) => (
        <span key={k}>{i > 0 && ', '}<code>{k} = {formatValue(v)}</code></span>
      ))}
    </>
  )
}

/** Copies text to the clipboard; says so visibly and to screen readers. */
export function CopyButton({ text, what }) {
  const [state, setState] = useState('idle')
  useEffect(() => {
    if (state === 'idle') return undefined
    const t = setTimeout(() => setState('idle'), 2500)
    return () => clearTimeout(t)
  }, [state])
  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setState('copied')
    } catch {
      setState('failed')
    }
  }
  return (
    <span className="copy">
      <button type="button" className="btn ghost small copy-btn" onClick={copy}>
        <Icon name={state === 'copied' ? 'check' : 'copy'} size={15} />
        {state === 'copied' ? 'Copied' : 'Copy'}<span className="sr-only"> {what}</span>
      </button>
      <span role="status" className={state === 'failed' ? 'form-msg error small' : 'sr-only'}>
        {state === 'copied' ? `${what} copied to the clipboard` : ''}
        {state === 'failed' ? 'Copy failed. Select the text and copy it.' : ''}
      </span>
    </span>
  )
}

/** A command or other copyable text block with its copy button. */
export function CommandBlock({ command, what }) {
  return (
    <div className="cmd">
      <pre tabIndex={0} aria-label={what}><code>{command}</code></pre>
      <CopyButton text={command} what={what} />
    </div>
  )
}

/**
 * Modal dialog on the native <dialog> element: the browser traps focus, Escape closes it,
 * and focus returns to whatever opened it.
 */
export function Modal({ open, title, onClose, children, wide }) {
  const ref = useRef(null)
  const opener = useRef(null)
  const titleId = useId()
  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) {
      opener.current = document.activeElement
      dialog.showModal()
    } else if (!open && dialog.open) {
      dialog.close()
    }
    if (!open && opener.current) {
      opener.current.focus?.()
      opener.current = null
    }
  }, [open])
  return (
    <dialog ref={ref} className={`modal ${wide ? 'wide' : ''}`} aria-labelledby={titleId}
      onCancel={(e) => { e.preventDefault(); onClose() }}>
      {open && (
        <div className="modal-inner">
          <header className="modal-head">
            <h2 id={titleId}>{title}</h2>
            <button type="button" className="btn ghost small icon-only" onClick={onClose}>
              <Icon name="close" size={16} /><span className="sr-only">Close</span>
            </button>
          </header>
          {children}
        </div>
      )}
    </dialog>
  )
}

/** Inline result of a save: "Saved." in green, errors in red. Announced politely. */
export function FormMessage({ message }) {
  return <span role="status" className={`form-msg ${message?.tone || ''}`}>{message?.text}</span>
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

/** { user, guest, demo, version, authConfigured, org, assessments, assessmentId, setAssessmentId, refresh } */
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
