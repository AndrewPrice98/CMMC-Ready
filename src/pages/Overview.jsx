import { Link } from 'react-router-dom'
import { api } from '../api.js'
import { FamilyHeatmap, HeatmapLegend, ScoreGauge, scoreTone } from '../components/charts.jsx'
import {
  Chip, DISCLAIMER, ErrorState, Icon, Loading, POAM_CITATION, THRESHOLD, cmmcId, formatDate, listWords,
  plural, useAsync, usePageTitle, useSession,
} from '../components/ui.jsx'

const SSP = '3.12.4'

function idKey(id) {
  return id.split('.').map(Number)
}

function byId(a, b) {
  const x = idKey(a)
  const y = idKey(b)
  for (let i = 0; i < Math.max(x.length, y.length); i += 1) {
    if ((x[i] ?? 0) !== (y[i] ?? 0)) return (x[i] ?? 0) - (y[i] ?? 0)
  }
  return 0
}

/** Requirements whose gap keeps the assessment from conditional status (32 CFR 170.21). */
export function poamBlockers(ov) {
  const eligible = new Set(ov.score.poam_eligible_ids)
  const ids = ov.score.deductions.filter((d) => !eligible.has(d.req_id)).map((d) => d.req_id)
  // 3.12.4 carries no points, so it never appears as a deduction, but it can't go on a POA&M.
  if (ov.ssp_missing && !ids.includes(SSP)) ids.push(SSP)
  return ids.sort(byId)
}

/** One sentence on conditional Level 2 status, computed from the score and POA&M rules. */
export function verdict(ov) {
  const score = ov.score.score
  const blockers = poamBlockers(ov)
  const gaps = ov.score.deductions.length + (ov.ssp_missing && !ov.score.deductions.some((d) => d.req_id === SSP) ? 1 : 0)
  const names = listWords(blockers.map(cmmcId))
  const cant = `can't be placed on a POA&M under ${POAM_CITATION}`
  if (score >= THRESHOLD) {
    if (!blockers.length && !gaps) {
      return { tone: 'good', text: 'Every requirement is met or not applicable: the maximum score of 110.' }
    }
    if (!blockers.length) {
      return {
        tone: 'good',
        text: `Meets the ${THRESHOLD}-point threshold for conditional Level 2 status, and ${gaps === 1 ? 'the one open gap' : `all ${gaps} open gaps`} can go on a POA&M with closeout within 180 days.`,
      }
    }
    return {
      tone: 'warn',
      text: `Clears the ${THRESHOLD}-point threshold, but ${names} ${cant}, so conditional status needs ${blockers.length === 1 ? 'it' : 'them'} met first.`,
    }
  }
  const short = `${plural(THRESHOLD - score, 'point')} short of conditional status (${THRESHOLD})`
  if (!blockers.length) {
    return { tone: scoreTone(score), text: `${short}; every open gap could go on a POA&M.` }
  }
  return { tone: 'bad', text: `${short}, and ${names} ${cant}.` }
}

/** Keep CMMC identifiers such as IA.L2-3.5.3 on one line inside running text. */
function NoBreakIds({ text }) {
  return text.split(/([A-Z]{2}\.L2-[\d.]*\d)/).map((part, i) => (
    i % 2 ? <span key={i} className="nowrap">{part}</span> : part
  ))
}

function Banner({ tone, title, children }) {
  return (
    <div className={`banner ${tone}`} role="note">
      <Icon name="conflict" size={18} />
      <div><strong>{title}</strong> {children}</div>
    </div>
  )
}

function ScoreCard({ ov }) {
  const v = verdict(ov)
  const totals = ov.family_heatmap.reduce((acc, f) => {
    for (const k of ['met', 'not_met', 'na', 'not_assessed']) acc[k] += f[k]
    return acc
  }, { met: 0, not_met: 0, na: 0, not_assessed: 0 })
  return (
    <section className="card score-card" aria-labelledby="score-title">
      <div className="card-head">
        <h2 id="score-title">SPRS score</h2>
        {ov.provisional && (
          <Chip tone="warn" glyph="!" title="The score is computed but not final; see the note above.">Provisional</Chip>
        )}
      </div>
      <div className="score-body">
        <ScoreGauge score={ov.score.score} provisional={ov.provisional} />
        <div className="score-side">
          <p className={`verdict ${v.tone}`}><NoBreakIds text={v.text} /></p>
          <dl className="kv">
            <div>
              <dt>Conditional Level 2 status</dt>
              <dd>
                {ov.conditional_eligible
                  ? <Chip tone="good" glyph="✓">Eligible</Chip>
                  : <Chip tone="bad" glyph="✕">Not yet</Chip>}
              </dd>
            </div>
            <div><dt>Requirements met or N/A</dt><dd className="num">{totals.met + totals.na} of 110</dd></div>
            <div><dt>Not met</dt><dd className="num">{totals.not_met}</dd></div>
            <div><dt>Not assessed</dt><dd className="num">{totals.not_assessed}</dd></div>
            <div><dt>POA&amp;M-eligible gaps</dt><dd className="num">{ov.score.poam_eligible_ids.length}</dd></div>
          </dl>
        </div>
      </div>
    </section>
  )
}

function StartHere({ ov, texts }) {
  const top = ov.top_gaps[0]
  if (!top) {
    return (
      <section className="card start-card" aria-labelledby="start-title">
        <p className="eyebrow" id="start-title">Start here</p>
        <p className="start-title">No open gaps.</p>
        <p className="muted">Every requirement is met or not applicable. Review the evidence before you submit.</p>
      </section>
    )
  }
  const allowed = ov.score.poam_eligible_ids.includes(top.req_id)
  return (
    <section className="card start-card" aria-labelledby="start-title">
      <p className="eyebrow" id="start-title">Start here: biggest gap</p>
      <p className="start-title">
        <span className="id-text">{cmmcId(top.req_id)}</span>
      </p>
      <p className="start-text">{texts[top.req_id]}</p>
      <p className="muted">
        Meeting it adds {plural(top.points, 'point')}.{' '}
        {allowed
          ? 'It may go on a POA&M in the meantime.'
          : 'It can\'t go on a POA&M, so it has to be met for conditional status.'}
      </p>
      <Link className="btn primary" to={`/requirements/${top.req_id}`}>
        Open {top.req_id} <Icon name="arrow" size={16} />
      </Link>
    </section>
  )
}

function ConflictsCard({ count }) {
  return (
    <section className="card conflicts-card" aria-labelledby="conflicts-title">
      <h2 id="conflicts-title">Conflicts with evidence</h2>
      <p className="big-number num">{count}</p>
      <p className="muted">
        {count === 1 ? 'objective where' : 'objectives where'} the assessor&apos;s answer disagrees with what
        the collectors found. The assessor&apos;s answer stands and is what the score uses.
      </p>
      {count > 0 && (
        <Link className="btn secondary" to="/requirements?conflicts=1">
          Review conflicts <Icon name="arrow" size={16} />
        </Link>
      )}
    </section>
  )
}

function TopGaps({ ov, texts }) {
  const eligible = new Set(ov.score.poam_eligible_ids)
  return (
    <section className="card" aria-labelledby="gaps-title">
      <div className="card-head">
        <h2 id="gaps-title">What moves your score most</h2>
      </div>
      {ov.top_gaps.length === 0 ? (
        <p className="muted">Nothing left to gain.</p>
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
                  <span className="gap-text">{texts[g.req_id]}</span>
                </span>
                {eligible.has(g.req_id)
                  ? <Chip tone="neutral">POA&amp;M allowed</Chip>
                  : <Chip tone="bad" glyph="✕">POA&amp;M not allowed</Chip>}
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
          <p className="eyebrow">CMMC Level 2 · NIST SP 800-171 Rev 2</p>
          <h1 tabIndex={-1}>Overview</h1>
          <p className="muted">
            {ov.assessment.title} · started {formatDate(ov.assessment.started_at)}
            {ov.assessment.completed_at ? ` · completed ${formatDate(ov.assessment.completed_at)}` : ' · in progress'}
          </p>
        </div>
      </header>
      <p className="disclaimer">{ov.disclaimer || DISCLAIMER}</p>

      {ov.ssp_missing && (
        <Banner tone="bad" title="No System Security Plan.">
          {cmmcId(SSP)} is not met, so this assessment cannot be submitted to SPRS without an SSP.
          The score is still computed and is labelled provisional.
        </Banner>
      )}
      {!ov.ssp_missing && ov.provisional && (
        <Banner tone="warn" title="Provisional score.">
          {plural(notAssessed, 'requirement is', 'requirements are')} not assessed yet and {notAssessed === 1 ? 'is' : 'are'} scored as not met.
        </Banner>
      )}

      <div className="grid overview-grid">
        <ScoreCard ov={ov} />
        <div className="stack">
          <StartHere ov={ov} texts={texts} />
          <ConflictsCard count={ov.conflicts_count} />
        </div>
        <section className="card heat-card" aria-labelledby="heat-title">
          <div className="card-head">
            <h2 id="heat-title">Family heatmap</h2>
            <span className="muted small">Met / total · points lost</span>
          </div>
          <HeatmapLegend />
          <FamilyHeatmap rows={ov.family_heatmap} />
        </section>
        <TopGaps ov={ov} texts={texts} />
      </div>
    </div>
  )
}
