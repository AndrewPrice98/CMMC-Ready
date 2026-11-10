import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { FamilyHeatmap, HeatmapLegend, ScoreGauge } from '../components/charts.jsx'
import { conditionalStatus, verdict } from '../verdict.js'
import {
  Chip, ErrorState, Icon, Loading, cmmcId, formatDate, plural, useAsync, usePageTitle, useSession,
} from '../components/ui.jsx'

const SSP = '3.12.4'

/** Keep CMMC identifiers such as IA.L2-3.5.3 on one line inside running text. */
function NoBreakIds({ text }) {
  return text.split(/([A-Z]{2}\.L2-[\d.]*\d)/).map((part, i) => (
    i % 2 ? <span key={i} className="nowrap">{part}</span> : part
  ))
}

/** A one-line notice: tinted row, small icon, no coloured border. */
function Notice({ tone, title, children }) {
  return (
    <div className={`notice ${tone}`} role="note">
      <Icon name="conflict" size={16} />
      <p><strong>{title}</strong> {children}</p>
    </div>
  )
}

function Stat({ label, children, note }) {
  return (
    <div className="kpi">
      <dt>{label}</dt>
      <dd className="num">{children}</dd>
      {note && <dd className="kpi-note">{note}</dd>}
    </div>
  )
}

function ScorePanel({ ov, count }) {
  const v = verdict(ov)
  const status = conditionalStatus(ov)
  const totals = ov.family_heatmap.reduce((acc, f) => {
    for (const k of ['met', 'not_met', 'na', 'not_assessed']) acc[k] += f[k]
    return acc
  }, { met: 0, not_met: 0, na: 0, not_assessed: 0 })
  return (
    <section className="panel" aria-labelledby="score-title">
      <div className="panel-head">
        <h2 id="score-title">SPRS score</h2>
        <span className="status-line">
          Conditional Level 2 status <Chip tone={status.tone}>{status.label}</Chip>
        </span>
      </div>
      <div className="score-body">
        <ScoreGauge score={ov.score.score} provisional={ov.provisional} />
        <p className="verdict"><NoBreakIds text={v.text} /></p>
      </div>
      <dl className="kpis">
        <Stat label="Met or N/A">{totals.met + totals.na}<span className="kpi-of"> of 110</span></Stat>
        <Stat label="Not met">{totals.not_met}</Stat>
        <Stat label="Not assessed">{totals.not_assessed}</Stat>
        <Stat label="POA&M-eligible gaps">{ov.score.poam_eligible_ids.length}</Stat>
        <Stat label="Conflicts with evidence">
          {count}
          {count > 0 && (
            <Link className="kpi-link" to="/requirements?conflicts=1">
              Review <Icon name="arrow" size={13} />
              <span className="sr-only"> conflicts with evidence</span>
            </Link>
          )}
        </Stat>
      </dl>
      <p className="panel-foot">
        A conflict is an objective where the assessor&apos;s answer disagrees with what the collectors found.
        The assessor&apos;s answer stands and is what the score uses.
      </p>
    </section>
  )
}

/** The single biggest gap, as one plain row at the top of the content. */
function BiggestGap({ ov, texts }) {
  const top = ov.top_gaps[0]
  if (!top) {
    return (
      <p className="pointer-row">
        <strong>No open gaps.</strong> Every requirement is met or not applicable. Review the evidence before you submit.
      </p>
    )
  }
  const allowed = ov.score.poam_eligible_ids.includes(top.req_id)
  return (
    <p className="pointer-row">
      <strong>Biggest gap: <span className="id-text">{cmmcId(top.req_id)}</span>, {plural(top.points, 'point')}.</strong>{' '}
      <span className="pointer-text">{texts[top.req_id]}</span>{' '}
      {allowed
        ? 'It may go on a POA&M in the meantime.'
        : 'It can\'t go on a POA&M, so it has to be met for conditional status.'}{' '}
      <Link className="pointer-link" to={`/requirements/${top.req_id}`}>
        Open <span className="sr-only">{top.req_id}</span><Icon name="arrow" size={13} />
      </Link>
    </p>
  )
}

function TopGaps({ ov, texts }) {
  const eligible = new Set(ov.score.poam_eligible_ids)
  return (
    <section className="panel" aria-labelledby="gaps-title">
      <div className="panel-head">
        <h2 id="gaps-title">What moves your score most</h2>
        <span className="muted small">Points gained if met</span>
      </div>
      {ov.top_gaps.length === 0 ? (
        <p className="panel-body muted">Nothing left to gain.</p>
      ) : (
        <ol className="gap-list">
          {ov.top_gaps.map((g) => (
            <li key={g.req_id}>
              <Link to={`/requirements/${g.req_id}`} className="gap-row">
                <span className="gap-points num">
                  <span aria-hidden="true">+{g.points}</span>
                  <span className="sr-only">Worth {plural(g.points, 'point')}:</span>
                </span>
                <span className="gap-main">
                  <span className="gap-id id-text">{cmmcId(g.req_id)}</span>
                  <span className="gap-text" title={texts[g.req_id]}>{texts[g.req_id]}</span>
                </span>
                {eligible.has(g.req_id)
                  ? <span className="gap-poam muted">POA&amp;M allowed</span>
                  : <Chip tone="bad">POA&amp;M not allowed</Chip>}
              </Link>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

export default function Overview() {
  usePageTitle('Overview')
  const { assessmentId } = useSession()
  const { data, error, loading, reload } = useAsync(
    () => Promise.all([api.overview(assessmentId), api.requirements(assessmentId)]),
    [assessmentId],
  )
  if (loading && !data) return <Loading />
  if (error) return <ErrorState error={error} onRetry={reload} />
  const [ov, reqs] = data
  const texts = Object.fromEntries(reqs.items.map((r) => [r.id, r.text]))
  const notAssessed = ov.score.not_assessed

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1 tabIndex={-1}>Overview</h1>
          <p className="page-sub">
            {ov.assessment.title} · started {formatDate(ov.assessment.started_at)}
            {ov.assessment.completed_at ? ` · completed ${formatDate(ov.assessment.completed_at)}` : ' · in progress'}
          </p>
        </div>
      </header>

      {ov.ssp_missing && (
        <Notice tone="bad" title="No System Security Plan.">
          {cmmcId(SSP)} is not met, so this assessment cannot be submitted to SPRS without an SSP.
          The score is still computed and is labelled provisional.
        </Notice>
      )}
      {!ov.ssp_missing && ov.provisional && (
        <Notice tone="warn" title="Provisional score.">
          {plural(notAssessed, 'requirement is', 'requirements are')} not assessed yet and {notAssessed === 1 ? 'is' : 'are'} scored as not met.
        </Notice>
      )}

      <BiggestGap ov={ov} texts={texts} />

      <div className="stack">
        <ScorePanel ov={ov} count={ov.conflicts_count} />
        <div className="grid overview-grid">
          <section className="panel" aria-labelledby="heat-title">
            <div className="panel-head">
              <h2 id="heat-title">Family heatmap</h2>
              <span className="muted small">Met / total · points lost</span>
            </div>
            <div className="panel-body flush-top">
              <HeatmapLegend />
              <FamilyHeatmap rows={ov.family_heatmap} />
            </div>
          </section>
          <TopGaps ov={ov} texts={texts} />
        </div>
      </div>
    </div>
  )
}
