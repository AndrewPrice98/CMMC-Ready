import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api.js'
import { ScoreHistoryChart } from '../components/charts.jsx'
import {
  Chip, Empty, ErrorState, Icon, Loading, THRESHOLD, cmmcId, formatDate, plural, useAsync, usePageTitle, useSession,
} from '../components/ui.jsx'
import { CHANGE_KINDS, changeRows, signed } from '../history.js'

function standing(a) {
  if (a.provisional) return <Chip tone="warn">Provisional</Chip>
  if (a.score >= THRESHOLD) return <span className="status good"><i className="dot" aria-hidden="true" />{THRESHOLD} or more</span>
  return <span className="status bad"><i className="dot" aria-hidden="true" />Below {THRESHOLD}</span>
}

function ScoresTable({ assessments }) {
  const { assessmentId, setAssessmentId } = useSession()
  const navigate = useNavigate()
  return (
    <div className="table-wrap panel flush">
      <table className="table history-table">
        <caption className="sr-only">SPRS score for each assessment, oldest first, with the change from the one before.</caption>
        <thead>
          <tr>
            <th scope="col">Assessment</th>
            <th scope="col">Date</th>
            <th scope="col" className="right">Score</th>
            <th scope="col" className="right">Change</th>
            <th scope="col">Standing</th>
          </tr>
        </thead>
        <tbody>
          {assessments.map((a, i) => {
            const delta = i > 0 ? a.score - assessments[i - 1].score : null
            return (
              <tr key={a.id}>
                <td className="title-cell">
                  <button type="button" className="link" onClick={() => { setAssessmentId(a.id); navigate('/') }}>
                    {a.title}<span className="sr-only">: open its overview</span>
                  </button>
                  {a.id === assessmentId && <span className="muted small"> · selected</span>}
                </td>
                <td className="date-cell" data-label="Date">{formatDate(a.date)}</td>
                <td className="right num strong" data-label="Score">{signed(a.score).replace('+', '')}</td>
                <td className={`right num ${delta > 0 ? 'good-text' : delta < 0 ? 'bad-text' : ''}`} data-label="Change">
                  {delta === null ? '—' : signed(delta)}
                </td>
                <td className="status-cell">{standing(a)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function ReqLinks({ ids, tone }) {
  return (
    <ul className="req-chips">
      {ids.map((id) => (
        <li key={id}>
          <Link to={`/requirements/${id}`} className={`req-chip ${tone}`} title={cmmcId(id)}>{id}</Link>
        </li>
      ))}
    </ul>
  )
}

function ChangeCard({ row }) {
  return (
    <li className="change-card">
      <article aria-labelledby={`change-${row.from_id}-${row.to_id}`}>
        <header className="change-head">
          <h3 id={`change-${row.from_id}-${row.to_id}`}>
            {row.from?.title} <span className="muted arrow" aria-hidden="true"><Icon name="arrow" size={14} /></span>
            <span className="sr-only"> to </span> {row.to?.title}
          </h3>
          {row.delta !== null && (
            <Chip tone={row.delta > 0 ? 'good' : row.delta < 0 ? 'bad' : 'neutral'}>
              {signed(row.delta)} {Math.abs(row.delta) === 1 ? 'point' : 'points'}
            </Chip>
          )}
        </header>
        {row.total === 0 ? (
          <p className="muted">No requirement changed status.</p>
        ) : (
          <dl className="change-groups">
            {CHANGE_KINDS.filter(([key]) => row[key]?.length).map(([key, label, tone]) => (
              <div key={key} className="change-group">
                <dt>{label} <span className="muted num">({row[key].length})</span></dt>
                <dd><ReqLinks ids={row[key]} tone={tone} /></dd>
              </div>
            ))}
          </dl>
        )}
        {row.total > 0 && !row.regressed.length && (
          <p className="small muted no-regressions">No regressions: nothing that was met has slipped.</p>
        )}
      </article>
    </li>
  )
}

export default function History() {
  usePageTitle('History')
  const { guest } = useSession()
  const { data, error, loading, reload } = useAsync(() => api.history(), [])
  const rows = data ? changeRows(data) : []

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1 tabIndex={-1}>History</h1>
          <p className="page-sub">Every assessment for this organization, oldest first, and what changed between them.</p>
        </div>
      </header>
      {error && <ErrorState error={error} onRetry={reload} />}
      {loading && !data && <Loading />}
      {data && data.assessments.length === 0 && (
        <Empty>
          No assessments yet.{' '}
          {guest ? 'History appears once an administrator starts one.' : <><Link to="/scope">Start one on the Scope page</Link>.</>}
        </Empty>
      )}
      {data && data.assessments.length > 0 && (
        <>
          <div className="stack">
          <section className="panel" aria-labelledby="chart-title">
            <div className="panel-head">
              <h2 id="chart-title">SPRS score</h2>
              <span className="muted small">{plural(data.assessments.length, 'assessment')}</span>
            </div>
            <div className="panel-body">
              <ScoreHistoryChart assessments={data.assessments} formatDate={formatDate} />
            </div>
          </section>
          <section aria-labelledby="scores-title">
            <div className="section-head"><h2 id="scores-title">Assessments</h2></div>
            <ScoresTable assessments={data.assessments} />
          </section>
          <section className="panel" aria-labelledby="changes-title">
            <div className="panel-head">
              <h2 id="changes-title">What changed</h2>
              <p className="muted small">Requirement status, compared with the assessment before.</p>
            </div>
            {rows.length === 0
              ? <p className="panel-body muted">Changes appear once there are two assessments.</p>
              : <ol className="change-list">{rows.map((r) => <ChangeCard key={`${r.from_id}-${r.to_id}`} row={r} />)}</ol>}
          </section>
          </div>
        </>
      )}
    </div>
  )
}
