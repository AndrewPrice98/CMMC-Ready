import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import {
  Chip, Empty, ErrorState, FormMessage, Icon, Loading, Modal, POAM_CITATION, POAM_STATUS, Status, cmmcId,
  formatDate, plural, useAsync, usePageTitle, useSession,
} from '../components/ui.jsx'
import {
  CLOSEOUT_DAYS, POAM_STATUSES, assessmentDate, closeoutDeadline, dueFlags, milestoneProgress, openGaps, poamBody,
  poamSummary, todayIso, validatePoamForm,
} from '../poam.js'

/** The draft's weakness reads "Requirement 3.8.4 is not met: <text>"; the list shows just the text. */
function gapText(draft) {
  return draft.weakness.replace(/^Requirement [\d.]+ is not met: /, '')
}

function DueCell({ item, deadline, today }) {
  const flags = dueFlags(item, deadline, today)
  return (
    <span className="due">
      <span className="nowrap">{item.due_date ? formatDate(item.due_date) : 'No due date'}</span>
      {flags.overdue && <Chip tone="bad">Overdue</Chip>}
      {!flags.overdue && flags.beyondCloseout && (
        <Chip tone="warn" title={`Due after the closeout deadline of ${formatDate(deadline)}`}>
          After 180-day closeout
        </Chip>
      )}
      {flags.noDueDate && <Chip tone="warn">Needs a date</Chip>}
      {!flags.overdue && flags.daysLeft !== null && flags.daysLeft <= 30 && (
        <span className="small muted">{flags.daysLeft === 0 ? 'Due today' : `In ${plural(flags.daysLeft, 'day')}`}</span>
      )}
    </span>
  )
}

function Milestones({ milestones }) {
  const { done, total } = milestoneProgress(milestones)
  if (!total) return <span className="muted">None</span>
  return (
    <details className="milestones">
      <summary>{done} of {plural(total, 'milestone')} done</summary>
      <ul>
        {milestones.map((m, i) => (
          <li key={i} className={m.done ? 'done' : ''}>
            <span className="ms-glyph" aria-hidden="true"><Icon name={m.done ? 'circle-check' : 'circle'} size={14} /></span>
            <span>
              {m.description}
              <span className="sr-only">{m.done ? ' (done)' : ' (not done)'}</span>
              {m.due && <span className="muted small"> · {formatDate(m.due)}</span>}
            </span>
          </li>
        ))}
      </ul>
    </details>
  )
}

function emptyForm(source, deadline) {
  return {
    weakness: source?.weakness || '',
    remediation: source?.remediation || '',
    owner: source?.owner || '',
    due_date: source?.due_date || deadline || '',
    status: source?.status || 'open',
    milestones: (source?.milestones || []).map((m) => ({ description: m.description, due: m.due || '', done: Boolean(m.done) })),
  }
}

/** Create (from an eligible gap) or edit a POA&M item. */
function PoamEditor({ target, deadline, assessmentId, onClose, onSaved }) {
  const creating = !target.item
  const reqId = target.item?.req_id || target.draft.req_id
  const [form, setForm] = useState(() => emptyForm(target.item || target.draft, deadline))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const set = (changes) => setForm((f) => ({ ...f, ...changes }))
  const setMilestone = (i, changes) => set({ milestones: form.milestones.map((m, j) => (j === i ? { ...m, ...changes } : m)) })

  async function save(e) {
    e.preventDefault()
    if (busy) return
    const problem = validatePoamForm(form)
    if (problem) {
      setError(problem)
      return
    }
    setBusy(true)
    setError(null)
    try {
      if (creating) await api.createPoam(assessmentId, { req_id: reqId, ...poamBody(form) })
      else await api.updatePoam(assessmentId, target.item.id, poamBody(form))
    } catch (err) {
      setError(err.message)
      setBusy(false)
      return
    }
    setBusy(false)
    onSaved(creating ? `Added a POA&M item for ${reqId}.` : `Saved the POA&M item for ${reqId}.`)
  }

  const beyond = form.due_date && deadline && form.due_date > deadline
  return (
    <form className="poam-form" onSubmit={save} noValidate>
      <p className="muted small">
        <span className="id-text strong-text">{cmmcId(reqId)}</span> · closeout deadline {formatDate(deadline)}{' '}
        ({CLOSEOUT_DAYS} days after the assessment, {POAM_CITATION}).
      </p>
      <label className="field">
        <span>Weakness (required)</span>
        <textarea rows={3} maxLength={5000} value={form.weakness} required
          aria-invalid={!form.weakness.trim() && error ? 'true' : undefined}
          onChange={(e) => set({ weakness: e.target.value })} />
      </label>
      <label className="field">
        <span>Planned remediation</span>
        <textarea rows={3} maxLength={5000} value={form.remediation} onChange={(e) => set({ remediation: e.target.value })} />
      </label>
      <div className="form-row">
        <label className="field">
          <span>Owner</span>
          <input type="text" maxLength={255} value={form.owner} onChange={(e) => set({ owner: e.target.value })} />
        </label>
        <label className="field">
          <span>Due date</span>
          <input type="date" value={form.due_date} onChange={(e) => set({ due_date: e.target.value })}
            aria-describedby={beyond ? 'due-warning' : undefined} />
        </label>
        <label className="field">
          <span>Status</span>
          <select value={form.status} onChange={(e) => set({ status: e.target.value })}>
            {POAM_STATUSES.map((s) => <option key={s} value={s}>{POAM_STATUS[s].label}</option>)}
          </select>
        </label>
      </div>
      {beyond && (
        <p id="due-warning" className="form-msg warn">
          This is after the closeout deadline of {formatDate(deadline)}. Conditional status ends at 180 days.
        </p>
      )}
      <fieldset className="milestone-fields">
        <legend>Milestones</legend>
        {form.milestones.length === 0 && <p className="muted small">No milestones yet.</p>}
        {form.milestones.map((m, i) => (
          <div className="milestone-row" key={i}>
            <label className="field grow">
              <span>Milestone {i + 1}</span>
              <input type="text" maxLength={1000} value={m.description}
                onChange={(e) => setMilestone(i, { description: e.target.value })} />
            </label>
            <label className="field">
              <span>Due</span>
              <input type="date" value={m.due} onChange={(e) => setMilestone(i, { due: e.target.value })} />
            </label>
            <label className="check">
              <input type="checkbox" checked={m.done} onChange={(e) => setMilestone(i, { done: e.target.checked })} />
              <span>Done</span>
            </label>
            <button type="button" className="btn ghost small icon-only"
              onClick={() => set({ milestones: form.milestones.filter((_, j) => j !== i) })}>
              <Icon name="trash" size={14} /><span className="sr-only">Remove milestone {i + 1}</span>
            </button>
          </div>
        ))}
        <button type="button" className="btn ghost small" disabled={form.milestones.length >= 50}
          onClick={() => set({ milestones: [...form.milestones, { description: '', due: '', done: false }] })}>
          <Icon name="plus" size={14} /> Add milestone
        </button>
      </fieldset>
      {error && <div className="state error" role="alert">{error}</div>}
      <div className="form-actions modal-actions">
        <button className="btn primary" aria-disabled={busy ? 'true' : undefined}>
          {busy ? 'Saving…' : creating ? 'Add to POA&M' : 'Save changes'}
        </button>
        <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
      </div>
    </form>
  )
}

function ItemsTable({ items, deadline, today, guest, onEdit }) {
  return (
    <div className="table-wrap panel flush">
      <table className="table poam-table">
        <caption className="sr-only">
          POA&amp;M items with weakness, owner, milestones, due date and status.
        </caption>
        <thead>
          <tr>
            <th scope="col">Requirement</th>
            <th scope="col">Weakness and remediation</th>
            <th scope="col">Owner</th>
            <th scope="col">Milestones</th>
            <th scope="col">Due</th>
            <th scope="col">Status</th>
            {!guest && <th scope="col"><span className="sr-only">Actions</span></th>}
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td className="id-cell">
                <Link to={`/requirements/${item.req_id}`} className="req-link">
                  <span className="id-text strong">{item.req_id}</span>
                  <span className="cmmc-id">{cmmcId(item.req_id)}</span>
                </Link>
              </td>
              <td className="text-cell weakness-cell">
                <span className="clamp">{item.weakness}</span>
                {item.remediation && <span className="remediation clamp small">{item.remediation}</span>}
              </td>
              <td className="owner-cell" data-label="Owner">{item.owner || <span className="muted">Unassigned</span>}</td>
              <td className="ms-cell" data-label="Milestones"><Milestones milestones={item.milestones} /></td>
              <td className="due-cell" data-label="Due"><DueCell item={item} deadline={deadline} today={today} /></td>
              <td className="status-cell"><Status status={item.status} map={POAM_STATUS} /></td>
              {!guest && (
                <td className="action-cell">
                  <button type="button" className="btn ghost small" onClick={() => onEdit(item)}>
                    <Icon name="edit" size={14} /> Edit<span className="sr-only"> POA&amp;M item for {item.req_id}</span>
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function GapRow({ draft, children }) {
  return (
    <li className="gap-item">
      <div className="gap-item-main">
        <Link to={`/requirements/${draft.req_id}`} className="gap-id id-text">{cmmcId(draft.req_id)}</Link>
        <span className="gap-text">{gapText(draft)}</span>
        {children}
      </div>
      <span className="pts lost num" title="Points this gap costs">
        <span aria-hidden="true">−{draft.points}</span><span className="sr-only">{plural(draft.points, 'point')} lost</span>
      </span>
    </li>
  )
}

function Stat({ label, value, tone }) {
  return (
    <div className={`kpi ${tone || ''}`}>
      <dt>{label}</dt>
      <dd className="num">{value}</dd>
    </div>
  )
}

export default function Poam() {
  usePageTitle('POA&M')
  const { assessmentId, assessments, guest } = useSession()
  const assessment = assessments.find((a) => a.id === assessmentId)
  const { data, error, loading, reload } = useAsync(() => api.poam(assessmentId), [assessmentId])
  const [editing, setEditing] = useState(null) // { item } or { draft }
  const [message, setMessage] = useState(null)
  const deadline = closeoutDeadline(assessment)
  const today = todayIso()

  const summary = useMemo(() => (data ? poamSummary(data.items, deadline, today) : null), [data, deadline, today])
  const gaps = useMemo(() => (data ? openGaps(data.drafts, data.items) : null), [data])

  function saved(text) {
    setEditing(null)
    setMessage({ tone: 'ok', text })
    reload()
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1 tabIndex={-1}>POA&amp;M</h1>
          <p className="page-sub">
            Plan of action and milestones, {POAM_CITATION}. {assessment?.title}. Assessment date{' '}
            {formatDate(assessmentDate(assessment))}; every item must close out by{' '}
            <strong className="nowrap">{formatDate(deadline)}</strong> ({CLOSEOUT_DAYS} days).
          </p>
        </div>
      </header>

      {error && <ErrorState error={error} onRetry={reload} />}
      {loading && !data && <Loading />}
      {data && (
        <>
          <dl className="kpis auto panel">
            <Stat label="Items" value={summary.total} />
            <Stat label="Open" value={summary.open} />
            <Stat label="In progress" value={summary.in_progress} />
            <Stat label="Closed" value={summary.closed} />
            <Stat label="Overdue" value={summary.overdue} tone={summary.overdue ? 'bad' : ''} />
            <Stat label="Eligible gaps without an item" value={gaps.eligible.length} tone={gaps.eligible.length ? 'warn' : ''} />
            <Stat label="Gaps not allowed" value={gaps.notAllowed.length} tone={gaps.notAllowed.length ? 'bad' : ''} />
          </dl>

          <p className="page-msg"><FormMessage message={message} /></p>

          <section aria-labelledby="items-title" className="section">
            <div className="section-head">
              <h2 id="items-title">Items</h2>
              <p className="muted small">Overdue: past the due date and not closed. After 180-day closeout: due later than {formatDate(deadline)}.</p>
            </div>
            {data.items.length === 0
              ? <Empty>No POA&amp;M items yet.{!guest && gaps.eligible.length > 0 && ' Add one from the eligible gaps below.'}</Empty>
              : <ItemsTable items={data.items} deadline={deadline} today={today} guest={guest} onEdit={(item) => setEditing({ item })} />}
          </section>

          <div className="gaps-grid">
            <section className="panel" aria-labelledby="eligible-title">
              <div className="panel-head">
                <h2 id="eligible-title">Eligible gaps without an item</h2>
                <span className="count-tag num">{gaps.eligible.length}</span>
              </div>
              <div className="panel-body flush-top">
              <p className="muted small">
                Not-met requirements that {POAM_CITATION} allows on a POA&amp;M: weight 1, or 3.13.11 at the partial
                (not FIPS-validated) deduction.
              </p>
              {gaps.eligible.length === 0 ? (
                <p className="muted">Every eligible gap has an item.</p>
              ) : (
                <ul className="gap-items">
                  {gaps.eligible.map((d) => (
                    <GapRow key={d.req_id} draft={d}>
                      {guest ? (
                        <span className="muted small">Eligible, no item yet</span>
                      ) : (
                        <button type="button" className="btn secondary small" onClick={() => setEditing({ draft: d })}>
                          <Icon name="plus" size={14} /> Add to POA&amp;M<span className="sr-only"> {d.req_id}</span>
                        </button>
                      )}
                    </GapRow>
                  ))}
                </ul>
              )}
              </div>
            </section>
            <section className="panel" aria-labelledby="blocked-title">
              <div className="panel-head">
                <h2 id="blocked-title">Not allowed on a POA&amp;M</h2>
                <span className="count-tag num">{gaps.notAllowed.length}</span>
              </div>
              <div className="panel-body flush-top">
              <p className="muted small">
                These have to be met before conditional Level 2 status is possible.
              </p>
              {gaps.notAllowed.length === 0 ? (
                <p className="muted">None. Every not-met requirement may go on a POA&amp;M.</p>
              ) : (
                <ul className="gap-items">
                  {gaps.notAllowed.map((d) => (
                    <GapRow key={d.req_id} draft={d}>
                      <span className="not-allowed small">{d.reason}</span>
                    </GapRow>
                  ))}
                </ul>
              )}
              </div>
            </section>
          </div>
          <p className="muted small">
            Requirements that are not assessed yet are not listed here: answer their objectives first.
          </p>
        </>
      )}

      <Modal open={Boolean(editing)} wide onClose={() => setEditing(null)}
        title={editing?.item ? `Edit POA&M item: ${editing.item.req_id}` : `Add ${editing?.draft?.req_id || ''} to the POA&M`}>
        {editing && (
          <PoamEditor key={editing.item?.id || editing.draft?.req_id} target={editing} deadline={deadline}
            assessmentId={assessmentId} onClose={() => setEditing(null)} onSaved={saved} />
        )}
      </Modal>
    </div>
  )
}
