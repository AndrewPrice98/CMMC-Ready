import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BrowserRouter, Link, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { api } from './api.js'
import Overview from './pages/Overview.jsx'
import Requirements from './pages/Requirements.jsx'
import RequirementDetail from './pages/RequirementDetail.jsx'
import Evidence from './pages/Evidence.jsx'
import EvidenceDetail from './pages/EvidenceDetail.jsx'
import Poam from './pages/Poam.jsx'
import Documents from './pages/Documents.jsx'
import History from './pages/History.jsx'
import Scope from './pages/Scope.jsx'
import Login from './pages/Login.jsx'
import {
  DISCLAIMER, Empty, ErrorState, GITHUB_URL, Icon, Loading, LogoMark, SessionContext, usePageTitle, useSession,
} from './components/ui.jsx'

const NAV_GROUPS = [
  { label: 'Assess', items: [['/', 'Overview', 'overview'], ['/requirements', 'Requirements', 'requirements'],
    ['/evidence', 'Evidence', 'evidence'], ['/poam', 'POA&M', 'poam']] },
  { label: 'Report', items: [['/documents', 'Documents', 'documents'], ['/history', 'History', 'history']] },
  { label: 'Set up', items: [['/scope', 'Scope', 'scope']] },
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
      <LogoMark size={26} />
      <span className="brand-name">CMMC Ready</span>
    </NavLink>
  )
}

/** Bottom of the sidebar: version, and who is looking at the data. */
function SidebarStatus({ onLogout, onSignIn }) {
  const { user, guest, demo, authConfigured, version } = useSession()
  return (
    <div className="side-foot">
      {guest ? (
        <>
          <p className="side-status"><Icon name="lock" size={14} /> {demo ? 'Demo, read-only' : 'Read-only'}</p>
          {authConfigured && (
            <button type="button" className="side-link" onClick={onSignIn}>Sign in as admin to edit</button>
          )}
        </>
      ) : (
        <>
          <p className="side-status">{demo ? 'Demo · ' : ''}Signed in as <strong>{user}</strong></p>
          <button type="button" className="side-link" onClick={onLogout}>Sign out</button>
        </>
      )}
      <p className="side-version">v{version}</p>
    </div>
  )
}

function ContextBar({ onMenu, menuOpen }) {
  const { org, assessments, assessmentId, setAssessmentId } = useSession()
  return (
    <div className="topbar">
      <button type="button" className="icon-btn menu-btn" onClick={onMenu} aria-expanded={menuOpen}
        aria-controls="sidebar">
        <Icon name="menu" size={18} /><span className="sr-only">Menu</span>
      </button>
      <NavLink to="/" className="brand brand-compact" aria-label="CMMC Ready, overview">
        <LogoMark size={24} />
      </NavLink>
      <p className="org-name" title={org?.name}>{org?.name || 'No organization yet'}</p>
      <div className="topbar-right">
        {assessments.length > 0 && (
          <label className="assessment-picker">
            <span className="sr-only">Assessment</span>
            <select value={assessmentId ?? ''} onChange={(e) => setAssessmentId(Number(e.target.value))}>
              {assessments.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.title}{a.completed_at ? '' : ' (in progress)'}
                </option>
              ))}
            </select>
          </label>
        )}
        <a className="btn ghost small" href={GITHUB_URL} target="_blank" rel="noreferrer">
          GitHub <Icon name="external" size={14} />
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
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

/**
 * Shown instead of an assessment page when there is no assessment yet (a new, empty
 * database): admins are sent to Scope to set things up, guests are told why it is empty.
 */
function SetupPrompt({ title }) {
  usePageTitle(title)
  const { org, guest } = useSession()
  const steps = [
    ['Describe your organization', 'Name, CAGE codes and the CUI boundary.', Boolean(org)],
    ['List your assets', 'Group them by CMMC asset category.', false],
    ['Start an assessment', 'Then answer the 320 objectives and upload collector output.', false],
  ]
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1 tabIndex={-1}>{title}</h1>
          <p className="page-sub">Getting started</p>
        </div>
      </header>
      <section className="panel setup-card" aria-labelledby="setup-title">
        {guest ? (
          <>
            <h2 id="setup-title">No assessment yet</h2>
            <p className="muted">
              This instance has {org ? 'an organization but no assessment' : 'no organization or assessment'} yet.
              An administrator sets them up on the Scope page; until then there is nothing to score.
            </p>
            <Link className="btn secondary" to="/scope">View scope <Icon name="arrow" size={14} /></Link>
          </>
        ) : (
          <>
            <h2 id="setup-title">{org ? 'Start your first assessment' : 'Set up your organization to begin'}</h2>
            <p className="muted">
              {org
                ? `${org.name} is set up. Start an assessment on the Scope page to see the score, gaps and documents here.`
                : 'CMMC Ready needs an organization and an assessment before it can score anything. It takes a minute.'}
            </p>
            <ol className="setup-steps">
              {steps.map(([name, help, done], i) => (
                <li key={name} className={done ? 'done' : ''}>
                  <span className="setup-num" aria-hidden="true">{done ? <Icon name="check" size={14} /> : i + 1}</span>
                  <span>
                    <strong>{name}</strong>{done && <span className="sr-only"> (done)</span>}{' '}
                    <span className="muted">{help}</span>
                  </span>
                </li>
              ))}
            </ol>
            <Link className="btn primary" to={org ? '/scope#new-assessment' : '/scope'}>
              {org ? 'Start an assessment' : 'Set up the organization'} <Icon name="arrow" size={14} />
            </Link>
          </>
        )}
      </section>
    </div>
  )
}

/** Pages that need an assessment fall back to the setup prompt. */
function NeedsAssessment({ title, children }) {
  const { assessmentId } = useSession()
  return assessmentId == null ? <SetupPrompt title={title} /> : children
}

function Shell({ onLogout, onSignIn }) {
  const mainRef = useRef(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const { pathname } = useLocation()
  useFocusOnNavigate(mainRef)
  useEffect(() => { setMenuOpen(false) }, [pathname])
  useEffect(() => {
    if (!menuOpen) return undefined
    const onKey = (e) => { if (e.key === 'Escape') setMenuOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [menuOpen])
  return (
    <div className={`app ${menuOpen ? 'menu-open' : ''}`}>
      <a className="skip-link" href="#main">Skip to content</a>
      <aside className="sidebar" id="sidebar">
        <Brand />
        <nav className="nav" aria-label="Main">
          {NAV_GROUPS.map((group) => (
            <div key={group.label} className="nav-group">
              <p className="nav-label">{group.label}</p>
              <ul>
                {group.items.map(([to, label, icon]) => (
                  <li key={to}>
                    <NavLink to={to} end={to === '/'}><Icon name={icon} size={16} />{label}</NavLink>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
        <SidebarStatus onLogout={onLogout} onSignIn={onSignIn} />
      </aside>
      <div className="scrim" onClick={() => setMenuOpen(false)} aria-hidden="true" />
      <div className="column">
        <ContextBar onMenu={() => setMenuOpen((o) => !o)} menuOpen={menuOpen} />
        <main id="main" className="main" ref={mainRef}>
          <Routes>
            <Route path="/" element={<NeedsAssessment title="Overview"><Overview /></NeedsAssessment>} />
            <Route path="/requirements" element={<NeedsAssessment title="Requirements"><Requirements /></NeedsAssessment>} />
            <Route path="/requirements/:reqId"
              element={<NeedsAssessment title="Requirement"><RequirementDetail /></NeedsAssessment>} />
            <Route path="/evidence" element={<NeedsAssessment title="Evidence"><Evidence /></NeedsAssessment>} />
            <Route path="/evidence/:evidenceId"
              element={<NeedsAssessment title="Evidence"><EvidenceDetail /></NeedsAssessment>} />
            <Route path="/poam" element={<NeedsAssessment title="POA&M"><Poam /></NeedsAssessment>} />
            <Route path="/documents" element={<NeedsAssessment title="Documents"><Documents /></NeedsAssessment>} />
            <Route path="/history" element={<History />} />
            <Route path="/scope" element={<Scope />} />
            <Route path="*" element={<Empty><h1 tabIndex={-1} className="h-inline">Page not found.</h1></Empty>} />
          </Routes>
        </main>
        <footer className="footer">
          <p className="disclaimer">{DISCLAIMER}</p>
          <p className="footer-meta">
            NIST SP 800-171 Rev 2 · DoD Assessment Methodology v1.2.1 ·{' '}
            <a href={GITHUB_URL} target="_blank" rel="noreferrer">Source on GitHub<span className="sr-only"> (opens in a new tab)</span></a>
          </p>
        </footer>
      </div>
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

  /** Re-read the organization and assessments after Scope changes them; optionally select one. */
  const refresh = useCallback(async (selectId) => {
    const [org, assessments] = await Promise.all([api.organization(), api.assessments()])
    setState((s) => (s.phase === 'user' ? { ...s, org, assessments } : s))
    if (selectId != null) {
      storeAssessment(selectId)
      setAssessmentIdState(selectId)
    } else {
      setAssessmentIdState((current) => (
        assessments.some((a) => a.id === current) ? current : defaultAssessment(assessments)))
    }
  }, [])

  const session = useMemo(() => (state.phase === 'user' ? {
    user: state.user, guest: state.guest, demo: state.demo, version: state.version,
    authConfigured: state.authConfigured, org: state.org, assessments: state.assessments,
    assessmentId, setAssessmentId, refresh,
  } : null), [state, assessmentId, setAssessmentId, refresh])

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
        <Shell onLogout={logout}
          onSignIn={() => setState((s) => ({ ...s, phase: 'anon', canCancel: true, notice: undefined }))} />
      </BrowserRouter>
    </SessionContext.Provider>
  )
}

export default App
