import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api } from '../api.js'
import {
  ASSET_CATEGORIES, Chip, ErrorState, FormMessage, Icon, Loading, formatDate, plural, useAsync, usePageTitle,
  useSession,
} from '../components/ui.jsx'
import { todayIso } from '../poam.js'

const CAGE = /^[A-Za-z0-9]{5}$/

function splitCodes(text) {
  return text.split(/[\s,;]+/).map((c) => c.trim()).filter(Boolean)
}

// -- organization -----------------------------------------------------------------------------

function OrgView({ org }) {
  return (
    <div className="org-grid">
      <div>
        <h3>Organization</h3>
        <p className="org-title">{org.name}</p>
        <dl className="kv compact">
          <div><dt>CAGE code(s)</dt><dd>{org.cage_codes.length ? org.cage_codes.join(', ') : 'None recorded'}</dd></div>
        </dl>
        {org.description && <p className="prose">{org.description}</p>}
      </div>
      <div>
        <h3>CUI boundary</h3>
        <p className="boundary">{org.cui_boundary || <span className="muted">No boundary described yet.</span>}</p>
      </div>
    </div>
  )
}

function orgFields(org) {
  return {
    name: org?.name || '', cage: org?.cage_codes?.join(', ') || '',
    description: org?.description || '', boundary: org?.cui_boundary || '',
  }
}

function OrgForm({ org, onSaved }) {
  const initial = orgFields(org)
  const [form, setForm] = useState(initial)
  // After a save the server's copy (trimmed, CAGE codes upper-cased) becomes the form.
  useEffect(() => { setForm(orgFields(org)) }, [org])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)
  const set = (changes) => { setForm((f) => ({ ...f, ...changes })); setMessage(null) }
  const dirty = Object.keys(initial).some((k) => form[k] !== initial[k])
  const codes = splitCodes(form.cage)
  const badCode = codes.find((c) => !CAGE.test(c))

  async function save(e) {
    e.preventDefault()
    if (busy || (!dirty && org)) return
    if (!form.name.trim()) return setMessage({ tone: 'error', text: 'Enter the organization name.' })
    if (badCode) return setMessage({ tone: 'error', text: `"${badCode}" is not a CAGE code: use 5 letters or digits.` })
    setBusy(true)
    try {
      await api.saveOrganization({
        name: form.name.trim(), cage_codes: codes, description: form.description, cui_boundary: form.boundary,
      })
    } catch (err) {
      setBusy(false)
      return setMessage({ tone: 'error', text: err.message })
    }
    setBusy(false)
    setMessage({ tone: 'ok', text: org ? 'Saved.' : 'Organization created. Now add its assets and start an assessment.' })
    try { await onSaved() } catch { setMessage({ tone: 'warn', text: 'Saved, but the page could not refresh. Reload it.' }) }
  }

  return (
    <form className="org-form" onSubmit={save} noValidate>
      <div className="form-row">
        <label className="field grow">
          <span>Organization name (required)</span>
          <input type="text" maxLength={200} value={form.name} required autoComplete="organization"
            aria-invalid={message?.tone === 'error' && !form.name.trim() ? 'true' : undefined}
            onChange={(e) => set({ name: e.target.value })} />
        </label>
        <label className="field">
          <span>CAGE code(s), comma-separated</span>
          <input type="text" maxLength={200} value={form.cage} placeholder="e.g. 1ABC2"
            aria-invalid={badCode ? 'true' : undefined} onChange={(e) => set({ cage: e.target.value })} />
        </label>
      </div>
      <label className="field">
        <span>Description</span>
        <textarea rows={3} maxLength={5000} value={form.description}
          placeholder="What the company does and how many people work there."
          onChange={(e) => set({ description: e.target.value })} />
      </label>
      <label className="field">
        <span>CUI boundary</span>
        <textarea rows={5} maxLength={10000} value={form.boundary}
          placeholder="Which systems, sites and services process, store or transmit CUI, and what is outside the boundary."
          onChange={(e) => set({ boundary: e.target.value })} />
      </label>
      <div className="form-actions">
        <button className="btn primary small" aria-disabled={(org && !dirty) || busy ? 'true' : undefined}>
          {busy ? 'Saving…' : org ? 'Save organization' : 'Create organization'}
        </button>
        <FormMessage message={message} />
      </div>
    </form>
  )
}

// -- assets -----------------------------------------------------------------------------------

function AssetFields({ value, onChange, idPrefix }) {
  return (
    <>
      <div className="form-row">
        <label className="field grow">
          <span>Asset name (required)</span>
          <input type="text" maxLength={200} value={value.name} required name={`${idPrefix}-name`}
            onChange={(e) => onChange({ name: e.target.value })} />
        </label>
        <label className="field">
          <span>Category</span>
          <select value={value.category} onChange={(e) => onChange({ category: e.target.value })}>
            {ASSET_CATEGORIES.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
          </select>
        </label>
      </div>
      <p className="small muted category-help">
        {ASSET_CATEGORIES.find((c) => c.code === value.category)?.help}
      </p>
      <label className="field">
        <span>Description</span>
        <input type="text" maxLength={5000} value={value.description}
          onChange={(e) => onChange({ description: e.target.value })} />
      </label>
    </>
  )
}

function AssetItem({ asset, admin, onChanged }) {
  const [mode, setMode] = useState('view') // view | edit | confirm
  const [form, setForm] = useState(asset)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)
  const editButton = useRef(null)
  const wasEditing = useRef(false)

  useEffect(() => { setForm(asset) }, [asset])
  // Back from the edit form: return focus to its Edit button.
  useEffect(() => {
    if (mode === 'view' && wasEditing.current) editButton.current?.focus()
    wasEditing.current = mode !== 'view'
  }, [mode])

  async function run(action, done) {
    setBusy(true)
    setMessage(null)
    try {
      await action()
    } catch (err) {
      setBusy(false)
      return setMessage({ tone: 'error', text: err.message })
    }
    setBusy(false)
    done?.()
    onChanged()
  }

  if (mode === 'edit') {
    return (
      <li className="asset editing">
        <form onSubmit={(e) => {
          e.preventDefault()
          if (busy) return
          if (!form.name.trim()) return setMessage({ tone: 'error', text: 'Enter a name.' })
          run(() => api.updateAsset(asset.id, {
            name: form.name.trim(), category: form.category, description: form.description,
          }), () => setMode('view'))
        }}>
          <AssetFields value={form} idPrefix={`asset-${asset.id}`} onChange={(c) => setForm((f) => ({ ...f, ...c }))} />
          <div className="form-actions">
            <button className="btn primary small" aria-disabled={busy ? 'true' : undefined}>{busy ? 'Saving…' : 'Save asset'}</button>
            <button type="button" className="btn ghost small" onClick={() => { setForm(asset); setMode('view') }}>Cancel</button>
            <FormMessage message={message} />
          </div>
        </form>
      </li>
    )
  }
  return (
    <li className="asset">
      <div className="asset-main">
        <span className="asset-name">{asset.name}</span>
        {asset.description && <span className="asset-desc">{asset.description}</span>}
      </div>
      {admin && mode === 'view' && (
        <div className="asset-actions">
          <button type="button" className="btn ghost small" ref={editButton} onClick={() => setMode('edit')}>
            <Icon name="edit" size={14} /> Edit<span className="sr-only"> {asset.name}</span>
          </button>
          <button type="button" className="btn ghost small danger" onClick={() => setMode('confirm')}>
            <Icon name="trash" size={14} /> Delete<span className="sr-only"> {asset.name}</span>
          </button>
        </div>
      )}
      {admin && mode === 'confirm' && (
        <div className="asset-confirm" role="group" aria-label={`Delete ${asset.name}?`}>
          <span className="small strong-text">Delete this asset?</span>
          <button type="button" className="btn danger-solid small" autoFocus aria-disabled={busy ? 'true' : undefined}
            onClick={() => !busy && run(() => api.deleteAsset(asset.id))}>Delete</button>
          <button type="button" className="btn ghost small" onClick={() => setMode('view')}>Keep</button>
          <FormMessage message={message} />
        </div>
      )}
    </li>
  )
}

function AddAsset({ onAdded, disabled }) {
  const blank = { name: '', category: 'cui', description: '' }
  const [form, setForm] = useState(blank)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)

  async function add(e) {
    e.preventDefault()
    if (busy || disabled) return
    if (!form.name.trim()) return setMessage({ tone: 'error', text: 'Enter a name for the asset.' })
    setBusy(true)
    setMessage(null)
    try {
      await api.createAsset({ name: form.name.trim(), category: form.category, description: form.description })
    } catch (err) {
      setBusy(false)
      return setMessage({ tone: 'error', text: err.message })
    }
    setBusy(false)
    setMessage({ tone: 'ok', text: `Added ${form.name.trim()}.` })
    setForm({ ...blank, category: form.category })
    onAdded()
  }

  return (
    <form className="add-asset" onSubmit={add} noValidate aria-labelledby="add-asset-title">
      <h3 id="add-asset-title">Add an asset</h3>
      <fieldset disabled={disabled} className="plain">
        <AssetFields value={form} idPrefix="new-asset" onChange={(c) => { setForm((f) => ({ ...f, ...c })); setMessage(null) }} />
        <div className="form-actions">
          <button className="btn primary small" aria-disabled={busy ? 'true' : undefined}>
            <Icon name="plus" size={14} /> {busy ? 'Adding…' : 'Add asset'}
          </button>
          <FormMessage message={message} />
        </div>
      </fieldset>
    </form>
  )
}

function Assets({ org, admin }) {
  const { data, error, loading, reload } = useAsync(() => api.assets(), [org?.id])
  return (
    <section className="panel" aria-labelledby="assets-title">
      <div className="panel-head">
        <h2 id="assets-title">Asset inventory</h2>
        {data && <span className="muted small">{plural(data.length, 'asset')}</span>}
      </div>
      <div className="panel-body flush-top">
      <p className="muted small">Grouped by the asset categories of the CMMC Level 2 scoping guidance (32 CFR §170.19).</p>
      {error && <ErrorState error={error} onRetry={reload} />}
      {loading && !data && <Loading />}
      {data && (
        <div className="asset-groups">
          {ASSET_CATEGORIES.map((cat) => {
            const items = data.filter((a) => a.category === cat.code)
            return (
              <section key={cat.code} className={`asset-group ${cat.code}`} aria-labelledby={`cat-${cat.code}`}>
                <div className="asset-group-head">
                  <h3 id={`cat-${cat.code}`}>{cat.name}</h3>
                  <span className="count-tag num">{items.length}</span>
                </div>
                <p className="small muted cat-help">{cat.help}</p>
                {items.length === 0
                  ? <p className="small muted none">None recorded.</p>
                  : (
                    <ul className="asset-list">
                      {items.map((a) => <AssetItem key={a.id} asset={a} admin={admin} onChanged={reload} />)}
                    </ul>
                  )}
              </section>
            )
          })}
        </div>
      )}
      {admin && (
        <>
          {!org && <p className="small muted">Create the organization first; assets belong to it.</p>}
          <AddAsset onAdded={reload} disabled={!org} />
        </>
      )}
      </div>
    </section>
  )
}

// -- assessments ------------------------------------------------------------------------------

function NewAssessment({ assessments, disabled, onCreated, focusRequested }) {
  const [title, setTitle] = useState('')
  const [copyFrom, setCopyFrom] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)
  const titleInput = useRef(null)

  useEffect(() => {
    if (!focusRequested || disabled) return undefined
    // After the page heading takes focus on navigation, move it to this form.
    const t = setTimeout(() => {
      titleInput.current?.scrollIntoView({ block: 'center' })
      titleInput.current?.focus({ preventScroll: true })
    }, 350)
    return () => clearTimeout(t)
  }, [focusRequested, disabled])

  async function create(e) {
    e.preventDefault()
    if (busy || disabled) return
    if (!title.trim()) return setMessage({ tone: 'error', text: 'Give the assessment a title.' })
    setBusy(true)
    setMessage(null)
    let created
    try {
      created = await api.createAssessment({ title: title.trim(), copy_from: copyFrom ? Number(copyFrom) : null })
    } catch (err) {
      setBusy(false)
      return setMessage({ tone: 'error', text: err.message })
    }
    setBusy(false)
    setTitle('')
    setCopyFrom('')
    setMessage({ tone: 'ok', text: `Started “${created.title}”. It is now the selected assessment.`, id: created.id })
    try { await onCreated(created.id) } catch { setMessage({ tone: 'warn', text: 'Started, but the page could not refresh. Reload it.' }) }
  }

  return (
    <form className="new-assessment" id="new-assessment" onSubmit={create} noValidate aria-labelledby="new-assessment-title">
      <h3 id="new-assessment-title">Start a new assessment</h3>
      <fieldset disabled={disabled} className="plain">
        <label className="field">
          <span>Title (required)</span>
          <input ref={titleInput} type="text" maxLength={200} value={title} placeholder="e.g. Annual self-assessment, 2027"
            onChange={(e) => { setTitle(e.target.value); setMessage(null) }} />
        </label>
        <label className="field">
          <span>Starting answers</span>
          <select value={copyFrom} onChange={(e) => setCopyFrom(e.target.value)}>
            <option value="">Start blank: every objective unanswered</option>
            {assessments.map((a) => <option key={a.id} value={a.id}>Copy answers from: {a.title}</option>)}
          </select>
        </label>
        <p className="small muted">
          Copying brings over answers, notes, justifications, organization-defined parameters and partial credit.
          Evidence and POA&amp;M items are not copied: upload fresh collector output.
        </p>
        <div className="form-actions">
          <button className="btn primary small" aria-disabled={busy ? 'true' : undefined}>
            <Icon name="plus" size={14} /> {busy ? 'Starting…' : 'Start assessment'}
          </button>
          <FormMessage message={message} />
        </div>
        {message?.id && <Link to="/" className="small">Go to the overview <Icon name="arrow" size={14} /></Link>}
      </fieldset>
    </form>
  )
}

function Assessments({ org, admin, focusNew }) {
  const { assessments, assessmentId, setAssessmentId, refresh } = useSession()
  const [message, setMessage] = useState(null)

  async function complete(a) {
    setMessage(null)
    try {
      await api.updateAssessment(a.id, { completed_at: todayIso() })
      await refresh()
      setMessage({ tone: 'ok', text: `Marked “${a.title}” completed.` })
    } catch (err) {
      setMessage({ tone: 'error', text: err.message })
    }
  }

  return (
    <section className="panel" aria-labelledby="assessments-title">
      <div className="panel-head">
        <h2 id="assessments-title">Assessments</h2>
        <span className="muted small">{plural(assessments.length, 'assessment')}</span>
      </div>
      <div className="panel-body flush-top">
      {assessments.length === 0 ? (
        <p className="muted">No assessments yet.</p>
      ) : (
        <ul className="assessment-list">
          {assessments.map((a) => (
            <li key={a.id} className={a.id === assessmentId ? 'current' : ''}>
              <div className="assessment-main">
                <span className="assessment-title">{a.title}</span>
                <span className="small muted">
                  Started {formatDate(a.started_at)} · {a.completed_at ? `completed ${formatDate(a.completed_at)}` : 'in progress'}
                </span>
              </div>
              <div className="assessment-side">
                <span className="num strong">{a.score < 0 ? `−${Math.abs(a.score)}` : a.score}</span>
                {a.provisional && <Chip tone="warn">Provisional</Chip>}
                {a.id === assessmentId
                  ? <Chip tone="info">Selected</Chip>
                  : (
                    <button type="button" className="btn ghost small" onClick={() => setAssessmentId(a.id)}>
                      Select<span className="sr-only"> {a.title}</span>
                    </button>
                  )}
                {admin && !a.completed_at && (
                  <button type="button" className="btn ghost small" onClick={() => complete(a)}>
                    Mark completed<span className="sr-only"> {a.title}</span>
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="page-msg"><FormMessage message={message} /></p>
      {admin && (
        <>
          {!org && <p className="small muted">Create the organization first.</p>}
          <NewAssessment assessments={assessments} disabled={!org} focusRequested={focusNew}
            onCreated={(id) => refresh(id)} />
        </>
      )}
      </div>
    </section>
  )
}

// -- organization-defined parameters -----------------------------------------------------------

function Parameters({ assessmentId, admin }) {
  const { data, error, loading, reload, setData } = useAsync(() => api.overview(assessmentId), [assessmentId])
  const [values, setValues] = useState(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)
  useEffect(() => { if (data) setValues(Object.fromEntries(Object.entries(data.odp).map(([k, v]) => [k, String(v)]))) }, [data])

  if (error) return <ErrorState error={error} onRetry={reload} />
  if (loading && !data) return <Loading />
  if (!values) return null
  const names = Object.keys(data.odp)
  const changed = names.filter((k) => values[k] !== String(data.odp[k]))

  async function save(e) {
    e.preventDefault()
    if (busy || !changed.length) return
    const body = {}
    for (const k of changed) {
      const n = Number(values[k])
      if (!values[k].trim() || !Number.isFinite(n) || n <= 0) {
        return setMessage({ tone: 'error', text: `${data.odp_descriptions[k] || k} must be a positive number.` })
      }
      body[k] = n
    }
    setBusy(true)
    setMessage(null)
    try {
      const res = await api.odp(assessmentId, body)
      setData({ ...data, odp: res.odp })
      setMessage({ tone: 'ok', text: `Saved. Re-checked ${plural(res.reevaluated, 'evidence file')} against the new values.` })
    } catch (err) {
      setMessage({ tone: 'error', text: err.message })
    }
    setBusy(false)
  }

  return (
    <form onSubmit={save} noValidate>
      <ul className="odp-list">
        {names.map((k) => (
          <li key={k}>
            {admin ? (
              <label className="odp-row">
                <span>{data.odp_descriptions[k] || k}</span>
                <input type="number" min="1" step="1" inputMode="numeric" value={values[k]}
                  onChange={(e) => { setValues({ ...values, [k]: e.target.value }); setMessage(null) }} />
              </label>
            ) : (
              <div className="odp-row">
                <span>{data.odp_descriptions[k] || k}</span>
                <span className="num strong">{data.odp[k]}</span>
              </div>
            )}
          </li>
        ))}
      </ul>
      {admin && (
        <div className="form-actions">
          <button className="btn primary small" aria-disabled={!changed.length || busy ? 'true' : undefined}>
            {busy ? 'Saving…' : 'Save parameters'}
          </button>
          <FormMessage message={message} />
        </div>
      )}
    </form>
  )
}

// -- page -------------------------------------------------------------------------------------

export default function Scope() {
  usePageTitle('Scope')
  const { org, guest, assessmentId, assessments, refresh } = useSession()
  const location = useLocation()
  const admin = !guest
  const current = assessments.find((a) => a.id === assessmentId)

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1 tabIndex={-1}>Scope</h1>
          <p className="page-sub">
            CMMC Level 2 scoping. The organization, its CUI boundary and the assets inside it. The System Security Plan export is built from this page.
          </p>
        </div>
      </header>

      {!org && admin && (
        <div className="notice info" role="note">
          <Icon name="info" size={16} />
          <p><strong>Set up your organization to begin.</strong> Describe it and its CUI boundary, list its assets, then start an assessment.</p>
        </div>
      )}

      <section className="panel org-card" aria-labelledby="org-title">
        <div className="panel-head">
          <h2 id="org-title">{org ? 'Organization and CUI boundary' : admin ? 'Your organization' : 'Organization'}</h2>
        </div>
        <div className="panel-body">
          {admin
            ? <OrgForm org={org} onSaved={() => refresh()} />
            : org ? <OrgView org={org} /> : <p className="muted">No organization has been set up yet.</p>}
        </div>
      </section>

      <div className="scope-grid">
        <Assets org={org} admin={admin} />
        <div className="stack">
          <Assessments org={org} admin={admin} focusNew={location.hash === '#new-assessment'} />
          {assessmentId != null && (
            <section className="panel" aria-labelledby="odp-title">
              <div className="panel-head"><h2 id="odp-title">Organization-defined parameters</h2></div>
              <div className="panel-body flush-top">
                <p className="muted small">
                  For {current?.title || 'the selected assessment'}. The collectors&apos; findings are judged against these values;
                  changing one re-checks the uploaded evidence.
                </p>
                <Parameters assessmentId={assessmentId} admin={admin} />
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  )
}
