import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BrowserRouter, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { api } from './api.js'
import Overview from './pages/Overview.jsx'
import Requirements from './pages/Requirements.jsx'
import RequirementDetail from './pages/RequirementDetail.jsx'
import Login from './pages/Login.jsx'
import {
  ComingSoon, DISCLAIMER, Empty, ErrorState, GITHUB_URL, Icon, Loading, SessionContext, useSession,
} from './components/ui.jsx'

const NAV = [
  ['/', 'Overview'],
  ['/requirements', 'Requirements'],
  ['/evidence', 'Evidence'],
  ['/poam', 'POA&M'],
  ['/documents', 'Documents'],
  ['/history', 'History'],
  ['/scope', 'Scope'],
]

const STORE_KEY = 'cmmcready.assessment'

function readStoredAssessment() {
  try { return window.localStorage.getItem(STORE_KEY) } catch { return null }
}

function storeAssessment(id) {
  try { window.localStorage.setItem(STORE_KEY, String(id)) } catch { /* private mode: not remembered */ }
}

/** The assessment in progress, else the most recent one. */
function defaultAssessment(list) {
  const stored = readStoredAssessment()
  if (stored && list.some((a) => String(a.id) === stored)) return Number(stored)
  return (list.find((a) => !a.completed_at) || list[0])?.id ?? null
}

function Brand() {
  return (
    <NavLink to="/" className="brand" aria-label="CMMC Ready, overview">
      <span className="brand-mark" aria-hidden="true"><Icon name="shield" size={20} /></span>
      <span className="brand-text">
        <span className="brand-name">CMMC Ready</span>
        <span className="brand-sub">Level 2 self-assessment</span>
      </span>
    </NavLink>
  )
}

function AccountArea({ onLogout, onSignIn }) {
  const { user, guest, demo, authConfigured } = useSession()
  if (guest) {
    return (
      <div className="account">
        <span className="badge demo" title="Hosted demo with a fictional company. Browsing is read-only.">
          <Icon name="lock" size={14} /> Demo · read-only
        </span>
        {authConfigured && (
          <button type="button" className="btn ghost small" onClick={onSignIn}>Sign in</button>
        )}
      </div>
    )
  }
  return (
    <div className="account">
      {demo && <span className="badge demo" title="Hosted demo with a fictional company.">Demo</span>}
      <span className="account-user">{user}</span>
      <button type="button" className="btn ghost small" onClick={onLogout}>Sign out</button>
    </div>
  )
}

function ContextBar({ org, onSignIn }) {
  const { assessments, assessmentId, setAssessmentId, guest, authConfigured } = useSession()
  return (
    <div className="contextbar">
      <div className="contextbar-inner">
        <div className="org">
          <span className="org-label">Organization</span>
          <span className="org-name">{org?.name || 'No organization yet'}</span>
        </div>
        {assessments.length > 0 && (
          <label className="assessment-picker">
            <span>Assessment</span>
            <select value={assessmentId ?? ''} onChange={(e) => setAssessmentId(Number(e.target.value))}>
              {assessments.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.title}{a.completed_at ? '' : ' (in progress)'}
                </option>
              ))}
            </select>
          </label>
        )}
        {guest && authConfigured && (
          <p className="edit-hint">
            <Icon name="lock" size={14} /> Read-only.{' '}
            <button type="button" className="link" onClick={onSignIn}>Sign in as admin to edit</button>
          </p>
        )}
      </div>
    </div>
  )
}

/** Move focus to the page heading after navigation so screen readers announce the new page. */
function useFocusOnNavigate(mainRef) {
  const { pathname } = useLocation()
  const previous = useRef(pathname)
  useEffect(() => {
    if (previous.current === pathname) return undefined
    previous.current = pathname
    window.scrollTo(0, 0)
    // The new page may still be loading; focus its heading as soon as it renders.
    let frame = 0
    const started = performance.now()
    const tryFocus = () => {
      const heading = mainRef.current?.querySelector('h1')
      if (heading) heading.focus({ preventScroll: true })
      else if (performance.now() - started < 3000) frame = requestAnimationFrame(tryFocus)
    }
    frame = requestAnimationFrame(tryFocus)
    return () => cancelAnimationFrame(frame)
  }, [pathname, mainRef])
}

function Shell({ org, onLogout, onSignIn }) {
  const { version, assessmentId } = useSession()
  const mainRef = useRef(null)
  useFocusOnNavigate(mainRef)
  return (
    <div className="app">
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="topbar">
        <div className="topbar-inner">
          <Brand />
          <nav className="nav" aria-label="Main">
            <ul>
              {NAV.map(([to, label]) => (
                <li key={to}><NavLink to={to} end={to === '/'}>{label}</NavLink></li>
              ))}
            </ul>
          </nav>
          <div className="topbar-right">
            <a className="gh-link" href={GITHUB_URL} target="_blank" rel="noreferrer">
              <Icon name="github" size={18} /><span>GitHub</span>
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
            <AccountArea onLogout={onLogout} onSignIn={onSignIn} />
          </div>
        </div>
      </header>
      <ContextBar org={org} onSignIn={onSignIn} />
      <main id="main" className="main" ref={mainRef}>
        {assessmentId == null ? (
          <Empty>No assessment exists yet. Sign in as admin and create one to start.</Empty>
        ) : (
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/requirements" element={<Requirements />} />
            <Route path="/requirements/:reqId" element={<RequirementDetail />} />
            <Route path="/evidence" element={<ComingSoon title="Evidence">
              Collector uploads and the findings they produced, objective by objective.</ComingSoon>} />
            <Route path="/poam" element={<ComingSoon title="POA&M">
              The plan of action and milestones, with the 32 CFR §170.21 eligibility rules and 180-day closeout dates.</ComingSoon>} />
            <Route path="/documents" element={<ComingSoon title="Documents">
              System Security Plan and POA&M exports (DOCX and CSV) and the SPRS summary.</ComingSoon>} />
            <Route path="/history" element={<ComingSoon title="History">
              Score over time and what changed between assessments.</ComingSoon>} />
            <Route path="/scope" element={<ComingSoon title="Scope">
              The CUI boundary, asset categories and organization-defined parameters.</ComingSoon>} />
            <Route path="*" element={<Empty><h1 tabIndex={-1} className="h-inline">Page not found.</h1></Empty>} />
          </Routes>
        )}
      </main>
      <footer className="footer">
        <div className="footer-inner">
          <p className="disclaimer">{DISCLAIMER}</p>
          <p className="footer-meta">
            CMMC Ready v{version} · NIST SP 800-171 Rev 2 · DoD Assessment Methodology v1.2.1 ·{' '}
            <a href={GITHUB_URL} target="_blank" rel="noreferrer">Source on GitHub<span className="sr-only"> (opens in a new tab)</span></a>
          </p>
        </div>
      </footer>
    </div>
  )
}

function App() {
  // checking -> (anon | user); 'unconfigured' when the server has no admin set up
  const [state, setState] = useState({ phase: 'checking' })
  const [assessmentId, setAssessmentIdState] = useState(null)

  const check = useCallback(async () => {
    try {
      const health = await api.health()
      const base = { version: health.version, demo: health.demo, authConfigured: health.auth_configured }
      if (!health.guest && !health.auth_configured) return setState({ phase: 'unconfigured' })
      let me
      try {
        me = await api.me()
      } catch (err) {
        if (err.status === 401) return setState({ phase: 'anon', ...base })
        throw err
      }
      const [org, assessments] = await Promise.all([api.organization(), api.assessments()])
      setAssessmentIdState(defaultAssessment(assessments))
      setState({ phase: 'user', user: me.username, guest: me.guest, org, assessments, ...base })
    } catch (error) {
      setState({ phase: 'error', error })
    }
  }, [])

  useEffect(() => { check() }, [check])

  // Any API call that comes back 401 (session expired) returns to the sign-in screen.
  useEffect(() => {
    const expire = () => setState((s) => (s.phase === 'user'
      ? { ...s, phase: 'anon', notice: 'Your session has expired. Sign in again.' }
      : s))
    window.addEventListener('cmmcready:unauthorized', expire)
    return () => window.removeEventListener('cmmcready:unauthorized', expire)
  }, [])

  const setAssessmentId = useCallback((id) => {
    storeAssessment(id)
    setAssessmentIdState(id)
  }, [])

  const session = useMemo(() => (state.phase === 'user' ? {
    user: state.user, guest: state.guest, demo: state.demo, version: state.version,
    authConfigured: state.authConfigured, assessments: state.assessments,
    assessmentId, setAssessmentId,
  } : null), [state, assessmentId, setAssessmentId])

  async function logout() {
    try { await api.logout() } catch { /* clearing local state is enough */ }
    // In demo mode this lands back on the guest view; otherwise on the sign-in page.
    await check()
  }

  if (state.phase === 'checking') return <div className="center-wrap"><Loading label="Connecting…" /></div>
  if (state.phase === 'error') {
    return <div className="center-wrap"><ErrorState error={state.error} onRetry={check} /></div>
  }
  if (state.phase === 'unconfigured') {
    return (
      <div className="center-wrap">
        <div className="state error" role="alert">
          No admin account is configured on the server. Run{' '}
          <code>python -m cmmcready create-admin</code> (or set the CMMCREADY_* environment variables
          on your host) and restart the API.
        </div>
      </div>
    )
  }
  if (state.phase === 'anon') {
    return (
      <Login notice={state.notice} onLogin={check}
        onCancel={state.canCancel ? () => setState((s) => ({ ...s, phase: 'user', canCancel: false })) : undefined} />
    )
  }
  return (
    <SessionContext.Provider value={session}>
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Shell org={state.org} onLogout={logout}
          onSignIn={() => setState((s) => ({ ...s, phase: 'anon', canCancel: true, notice: undefined }))} />
      </BrowserRouter>
    </SessionContext.Provider>
  )
}

export default App
