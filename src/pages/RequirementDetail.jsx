import { useEffect, useId, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { api } from '../api.js'
import {
  ANSWERS, Chip, ErrorState, FINDING_RESULTS, Icon, Loading, POAM_CITATION, StatusChip, cmmcId, formatDate,
  partialLabel, plural, useAsync, usePageTitle, useSession,
} from '../components/ui.jsx'

const COLLECTORS = { windows: 'Windows', m365: 'Microsoft 365 / Entra ID' }
const POAM_STATUS = {
  open: { label: 'Open', tone: 'warn', glyph: '○' },
  in_progress: { label: 'In progress', tone: 'info', glyph: '◐' },
  closed: { label: 'Closed', tone: 'good', glyph: '✓' },
}
const ANSWER_ORDER = ['met', 'not_met', 'na', 'unanswered']

function formatValue(value) {
  if (value === null || value === undefined) return 'none'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function Observed({ observed }) {
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

function Finding({ f, reqId }) {
  return (
    <li className={`finding ${f.result}`}>
      <div className="finding-head">
        <StatusChip status={f.result} map={FINDING_RESULTS} />
        <span className="finding-check">
          <span className="sr-only">Check </span><code>{f.check_id}</code>
          <span className="muted"> · rule {f.rule_id}</span>
        </span>
      </div>
      <dl className="finding-kv">
        <div><dt>Observed</dt><dd><Observed observed={f.observed} /></dd></div>
        <div><dt>Expected</dt><dd><code>{f.expected || '—'}</code></dd></div>
      </dl>
      <p className="finding-meta">
        {COLLECTORS[f.collector] || f.collector} collector · host <span className="mono break">{f.host}</span>
        {' '}· collected {formatDate(f.collected_at)}
      </p>
      {f.partial_hint && (
        <p className="finding-meta">Suggests partial credit: {partialLabel(reqId, f.partial_hint)}</p>
      )}
    </li>
  )
}

/** Both values side by side: what the assessor said, and what the evidence says. */
function ConflictFlag({ objective }) {
  const disagreeing = objective.answer === 'met'
    ? objective.findings.filter((f) => f.result === 'not_met')
    : objective.findings
  const evidenceResult = objective.answer === 'met' ? 'not_met' : 'met'
  const sources = [...new Set(disagreeing.map((f) => `${f.check_id} on ${f.host}`))]
  return (
    <div className="conflict-flag" role="note">
      <p className="conflict-title"><Icon name="conflict" size={18} /> Conflicts with evidence</p>
      <div className="conflict-values">
        <div>
          <span className="conflict-label">Assessor answer</span>
          <StatusChip status={objective.answer} map={ANSWERS} />
        </div>
        <span className="conflict-vs" aria-hidden="true">vs</span>
        <div>
          <span className="conflict-label">Collected evidence</span>
          <StatusChip status={evidenceResult} map={ANSWERS} />
          <span className="small conflict-source">from {sources.join('; ')}</span>
        </div>
      </div>
      <p className="small">The assessor&apos;s answer stands and is what the score uses. Review the evidence and update one or the other.</p>
    </div>
  )
}

function AnswerEditor({ objective, assessmentId, onSaved }) {
  const uid = useId()
  const [answer, setAnswer] = useState(objective.answer)
  const [note, setNote] = useState(objective.note || '')
  const [justification, setJustification] = useState(objective.justification || '')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)

  useEffect(() => {
    setAnswer(objective.answer)
    setNote(objective.note || '')
    setJustification(objective.justification || '')
  }, [objective.answer, objective.note, objective.justification])

  const dirty = answer !== objective.answer || note !== (objective.note || '')
    || justification !== (objective.justification || '')
  const needsJustification = answer === 'na' && !justification.trim()

  async function save(e) {
    e.preventDefault()
    if (needsJustification) {
      setMessage({ tone: 'error', text: 'Not applicable needs a justification.' })
      return
    }
    setBusy(true)
    setMessage(null)
    try {
      await api.answer(assessmentId, objective.id, { answer, note, justification: answer === 'na' ? justification : '' })
      await onSaved()
      setMessage({ tone: 'ok', text: 'Saved.' })
    } catch (err) {
      setMessage({ tone: 'error', text: err.message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="answer-form" onSubmit={save}>
      <fieldset className="segmented">
        <legend>Assessor answer</legend>
        {ANSWER_ORDER.map((value) => (
          <label key={value} className={`seg ${ANSWERS[value].tone} ${answer === value ? 'on' : ''}`}>
            <input type="radio" name={`${uid}-answer`} value={value} checked={answer === value}
              onChange={() => setAnswer(value)} />
            <span aria-hidden="true" className="chip-glyph">{ANSWERS[value].glyph}</span>
            {ANSWERS[value].label}
          </label>
        ))}
      </fieldset>
      {answer === 'na' && (
        <label className="field">
          <span>Justification (required for Not applicable)</span>
          <textarea rows={2} maxLength={5000} value={justification} required
            aria-invalid={needsJustification ? 'true' : undefined}
            onChange={(e) => setJustification(e.target.value)} />
        </label>
      )}
      <label className="field">
        <span>Assessor note</span>
        <textarea rows={3} maxLength={5000} value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      <div className="form-actions">
        <button className="btn primary small" disabled={!dirty || busy}>{busy ? 'Saving…' : 'Save answer'}</button>
        <span role="status" className={`form-msg ${message?.tone || ''}`}>{message?.text}</span>
      </div>
    </form>
  )
}

function Objective({ objective, guest, assessmentId, onSaved }) {
  const letter = objective.id.slice(objective.id.indexOf('['))
  const headingId = useId()
  return (
    <li className={`card objective ${objective.conflict ? 'has-conflict' : ''}`}>
      <article aria-labelledby={headingId}>
        <header className="objective-head">
          <h3 id={headingId}>
            <span className="mono obj-letter">{letter}</span>
            <span className="sr-only"> ({objective.id})</span>
            <span className="obj-text">Determine if {objective.text}</span>
          </h3>
          {guest && <StatusChip status={objective.answer} map={ANSWERS} />}
        </header>

        {objective.conflict && <ConflictFlag objective={objective} />}

        {guest ? (
          <>
            {objective.answer === 'na' && objective.justification && (
              <p className="note"><span className="note-label">Justification</span>{objective.justification}</p>
            )}
            {objective.note && <p className="note"><span className="note-label">Assessor note</span>{objective.note}</p>}
          </>
        ) : (
          <AnswerEditor objective={objective} assessmentId={assessmentId} onSaved={onSaved} />
        )}

        <div className="findings">
          <h4>Automated findings {objective.findings.length > 0 && <span className="muted">({objective.findings.length})</span>}</h4>
          {objective.findings.length === 0 ? (
            <p className="muted small">No collector check maps to this objective in the uploaded evidence.</p>
          ) : (
            <ul className="finding-list">
              {objective.findings.map((f, i) => <Finding key={`${f.evidence_id}-${f.check_id}-${f.rule_id}-${i}`} f={f} reqId={objective.id.split('[')[0]} />)}
            </ul>
          )}
        </div>
      </article>
    </li>
  )
}

function PartialCredit({ data, guest, assessmentId, onSaved }) {
  const req = data.requirement
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)
  const [selected, setSelected] = useState(data.partial_choice)
  useEffect(() => { setSelected(data.partial_choice) }, [data.partial_choice])
  const choices = [null, ...Object.keys(req.partial)]
  const points = (c) => (c === null ? req.weight : req.partial[c])

  async function choose(choice) {
    setSelected(choice)
    setBusy(true)
    setMessage(null)
    try {
      await api.partial(assessmentId, req.id, choice)
      await onSaved()
      setMessage({ tone: 'ok', text: 'Saved.' })
    } catch (err) {
      setSelected(data.partial_choice)
      setMessage({ tone: 'error', text: err.message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="partial">
      <h3>Partial credit</h3>
      <p className="small muted">DoD Assessment Methodology §5(e). Applies only while the requirement is not met.</p>
      {guest ? (
        <ul className="partial-list">
          {choices.map((c) => (
            <li key={String(c)} className={data.partial_choice === c ? 'on' : ''}>
              <span>{partialLabel(req.id, c)}</span>
              <span className="num">−{points(c)}</span>
              {data.partial_choice === c && <Chip tone="info" glyph="●">Selected</Chip>}
            </li>
          ))}
        </ul>
      ) : (
        <fieldset className="partial-options" disabled={busy}>
          <legend className="sr-only">Partial-credit choice for {req.id}</legend>
          {choices.map((c) => (
            <label key={String(c)} className={`radio-row ${selected === c ? 'on' : ''}`}>
              <input type="radio" name="partial" checked={selected === c} onChange={() => choose(c)} />
              <span>{partialLabel(req.id, c)}</span>
              <span className="num">−{points(c)}</span>
            </label>
          ))}
          <span role="status" className={`form-msg ${message?.tone || ''}`}>{message?.text}</span>
        </fieldset>
      )}
    </div>
  )
}

function PoamPanel({ data }) {
  const item = data.poam
  if (item) {
    const s = POAM_STATUS[item.status] || { label: item.status, tone: 'neutral' }
    return (
      <>
        <p><Chip tone={s.tone} glyph={s.glyph}>POA&amp;M: {s.label}</Chip></p>
        <dl className="kv compact">
          <div><dt>Due</dt><dd>{formatDate(item.due_date)}</dd></div>
          <div><dt>Owner</dt><dd>{item.owner || '—'}</dd></div>
        </dl>
        <p className="small"><span className="note-label">Weakness</span>{item.weakness}</p>
        {item.milestones?.length > 0 && (
          <p className="small muted">
            {item.milestones.filter((m) => m.done).length} of {plural(item.milestones.length, 'milestone')} done
          </p>
        )}
      </>
    )
  }
  if (data.poam_rule_reason) {
    return (
      <>
        <p><Chip tone="bad" glyph="✕">Not allowed on POA&amp;M</Chip></p>
        <p className="small">{data.poam_rule_reason}</p>
        {data.status !== 'met' && data.status !== 'na' && (
          <p className="small strong-text">It has to be met before conditional Level 2 status is possible.</p>
        )}
      </>
    )
  }
  if (data.status === 'met' || data.status === 'na') {
    return (
      <>
        <p><Chip tone="neutral">No POA&amp;M needed</Chip></p>
        <p className="small muted">
          The requirement is {data.status === 'met' ? 'met' : 'not applicable'}. If it became a gap, it could go on a
          POA&amp;M under {POAM_CITATION}.
        </p>
      </>
    )
  }
  return (
    <>
      <p><Chip tone="warn" glyph="○">Eligible, no item yet</Chip></p>
      <p className="small muted">This gap may go on a POA&amp;M under {POAM_CITATION}, with closeout within 180 days.</p>
    </>
  )
}

function Paragraphs({ text }) {
  return text.split(/\n\s*\n/).map((p, i) => <p key={i}>{p}</p>)
}

export default function RequirementDetail() {
  const { reqId } = useParams()
  const location = useLocation()
  const { assessmentId, guest } = useSession()
  usePageTitle(cmmcId(reqId))
  const from = typeof location.state?.from === 'string' && /^\?[\w=&%.+-]*$/.test(location.state.from)
    ? location.state.from : ''
  const backTo = `/requirements${from}`

  const { data, error, loading, reload, setData } = useAsync(
    () => api.requirement(assessmentId, reqId), [assessmentId, reqId])

  // Quiet refresh after a save: keep the page on screen, just update the numbers.
  const refresh = async () => setData(await api.requirement(assessmentId, reqId))

  const back = (
    <Link className="back-link" to={backTo}>
      <Icon name="back" size={16} /> {from ? 'Back to filtered requirements' : 'All requirements'}
    </Link>
  )

  if (loading && !data) return <div className="page">{back}<Loading /></div>
  if (error) {
    return (
      <div className="page">
        {back}
        <h1 tabIndex={-1} className="h-inline">{cmmcId(reqId)}</h1>
        <ErrorState error={error} onRetry={reload} />
      </div>
    )
  }

  const req = data.requirement
  const objectives = data.objectives
  const conflicts = objectives.filter((o) => o.conflict).length
  const counts = objectives.reduce((acc, o) => ({ ...acc, [o.answer]: (acc[o.answer] || 0) + 1 }), {})
  const objectiveSummary = ANSWER_ORDER.filter((a) => counts[a])
    .map((a) => `${counts[a]} ${ANSWERS[a].label.toLowerCase()}`).join(' · ')

  return (
    <div className="page detail">
      {back}
      <header className="page-head detail-head">
        <div>
          <p className="eyebrow">{req.family_name} · {req.family}</p>
          <h1 tabIndex={-1}>
            <span className="id-text">{cmmcId(req.id)}</span>
          </h1>
          <div className="chip-row">
            <StatusChip status={data.status} />
            <Chip tone="neutral">{req.basic ? 'Basic requirement' : 'Derived requirement'}</Chip>
            <Chip tone="neutral">Weight {req.weight}</Chip>
            {data.points_lost > 0 && <Chip tone="bad">−{data.points_lost} points</Chip>}
            {conflicts > 0 && <Chip tone="warn" glyph="!">{plural(conflicts, 'conflict')} with evidence</Chip>}
          </div>
        </div>
      </header>

      <div className="detail-grid">
        <div className="detail-main">
          <section className="card" aria-labelledby="text-title">
            <h2 id="text-title" className="eyebrow">Requirement {req.id} · NIST SP 800-171 Rev 2 (verbatim)</h2>
            <blockquote className="req-text">{req.text}</blockquote>
            {req.discussion && (
              <details className="disclosure">
                <summary>Discussion</summary>
                <div className="prose"><Paragraphs text={req.discussion} /></div>
              </details>
            )}
            {req.footnotes?.length > 0 && (
              <details className="disclosure">
                <summary>Footnotes ({req.footnotes.length})</summary>
                <ol className="prose footnotes">
                  {req.footnotes.map((f, i) => <li key={i}>{f}</li>)}
                </ol>
              </details>
            )}
          </section>

          <section aria-labelledby="obj-title">
            <div className="section-head">
              <h2 id="obj-title">Assessment objectives</h2>
              <p className="muted small">NIST SP 800-171A · {plural(objectives.length, 'objective')} · {objectiveSummary}</p>
            </div>
            {conflicts > 0 && (
              <div className="banner warn" role="note">
                <Icon name="conflict" size={18} />
                <div>
                  <strong>{plural(conflicts, 'objective conflicts', 'objectives conflict')} with collected evidence.</strong>{' '}
                  Both values are shown below. The assessor&apos;s answer stands and is what the score uses.
                </div>
              </div>
            )}
            <ol className="objective-list">
              {objectives.map((o) => (
                <Objective key={o.id} objective={o} guest={guest} assessmentId={assessmentId} onSaved={refresh} />
              ))}
            </ol>
          </section>
        </div>

        <aside className="detail-side" aria-label="Scoring and POA&M">
          <section className="card" aria-labelledby="scoring-title">
            <h2 id="scoring-title">Scoring</h2>
            <dl className="kv compact">
              <div>
                <dt>Weight</dt>
                <dd>{req.weight === 0 ? '0 (no deduction; NA in the DoD methodology)' : plural(req.weight, 'point')}</dd>
              </div>
              <div>
                <dt>Points lost now</dt>
                <dd className={data.points_lost ? 'lost num' : 'num'}>{data.points_lost ? `−${data.points_lost}` : '0'}</dd>
              </div>
              <div><dt>Objectives answered</dt><dd className="num">{objectives.filter((o) => o.answer !== 'unanswered').length} of {objectives.length}</dd></div>
            </dl>
            {req.partial && (
              <PartialCredit data={data} guest={guest} assessmentId={assessmentId} onSaved={refresh} />
            )}
          </section>
          <section className="card" aria-labelledby="poam-title">
            <h2 id="poam-title">POA&amp;M</h2>
            <PoamPanel data={data} />
          </section>
        </aside>
      </div>
    </div>
  )
}
