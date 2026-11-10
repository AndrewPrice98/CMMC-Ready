import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api.js'
import {
  COLLECTORS, Chip, CommandBlock, ErrorState, FINDING_RESULTS, Icon, Loading, Observed, StatusChip, formatDate,
  plural, useAsync, usePageTitle, useSession,
} from '../components/ui.jsx'

const FILTERS = [
  ['all', 'All checks'],
  ['not_met', 'Not met'],
  ['unavailable', 'Unavailable'],
]

/** Gaps first: not met, then unavailable, then not assessed, then met, then unmapped checks. */
function checkRank(c) {
  if (c.result === 'not_met') return 0
  if (c.status !== 'ok') return 1
  return { not_assessed: 2, met: 3 }[c.result] ?? 4
}

function yesNo(value) {
  if (value === true) return 'Yes'
  if (value === false) return 'No'
  return 'Not recorded'
}

function SourceFacts({ run }) {
  const s = run.source || {}
  if (run.collector === 'windows') {
    return (
      <dl className="kv compact">
        <div><dt>Computer</dt><dd className="break">{s.name || run.host}</dd></div>
        <div><dt>Operating system</dt><dd>{s.os || '—'}{s.build ? ` (build ${s.build})` : ''}</dd></div>
        <div><dt>Domain joined</dt><dd>{yesNo(s.domain_joined)}</dd></div>
        <div><dt>Run as administrator</dt><dd>{yesNo(s.elevated)}</dd></div>
      </dl>
    )
  }
  return (
    <dl className="kv compact">
      <div><dt>Tenant ID</dt><dd className="mono break">{s.id || run.host}</dd></div>
      <div><dt>Names redacted</dt><dd>{yesNo(s.names_redacted)}</dd></div>
    </dl>
  )
}

function CheckStatus({ check }) {
  if (check.status === 'ok') return <Chip tone="neutral" glyph="✓">Read</Chip>
  return <Chip tone="warn" glyph="!">Unavailable</Chip>
}

function CheckCard({ check }) {
  const reqOf = (objectiveId) => objectiveId.split('[')[0]
  const objectives = [...new Set(check.findings.map((f) => f.objective_id))]
  return (
    <li className={`card check-card ${check.result || 'none'}`}>
      <article aria-labelledby={`check-${check.id}`}>
        <header className="check-head">
          <h3 id={`check-${check.id}`}><code>{check.id}</code></h3>
          <div className="chip-row tight">
            <CheckStatus check={check} />
            {check.result
              ? <StatusChip status={check.result} map={FINDING_RESULTS} />
              : <Chip tone="outline">No mapped objectives</Chip>}
          </div>
        </header>
        {check.status !== 'ok' && (
          <p className="note"><span className="note-label">Why it is unavailable</span>{check.reason || 'No reason given.'}</p>
        )}
        {check.command && (
          <div className="check-command">
            <span className="note-label">Command it ran</span>
            <CommandBlock command={check.command} what={`command for ${check.id}`} />
          </div>
        )}
        {check.findings.length > 0 && (
          <div className="check-findings">
            <span className="note-label">
              Informs {plural(objectives.length, 'objective')}
            </span>
            <ul className="obj-findings">
              {check.findings.map((f, i) => (
                <li key={`${f.objective_id}-${f.rule_id}-${i}`} className={f.result}>
                  <div className="obj-finding-head">
                    <Link to={`/requirements/${reqOf(f.objective_id)}`} className="mono obj-link">{f.objective_id}</Link>
                    <StatusChip status={f.result} map={FINDING_RESULTS} />
                    <span className="muted small">rule {f.rule_id}</span>
                  </div>
                  <dl className="finding-kv">
                    <div><dt>Observed</dt><dd><Observed observed={f.observed} /></dd></div>
                    <div><dt>Expected</dt><dd><code>{f.expected || '—'}</code></dd></div>
                  </dl>
                </li>
              ))}
            </ul>
          </div>
        )}
        {check.value !== null && check.value !== undefined && (
          <details className="disclosure raw">
            <summary>Collected value</summary>
            <pre className="raw-json" tabIndex={0} aria-label={`Collected value for ${check.id}`}>
              {JSON.stringify(check.value, null, 2)}
            </pre>
          </details>
        )}
      </article>
    </li>
  )
}

export default function EvidenceDetail() {
  const { evidenceId } = useParams()
  const { assessmentId } = useSession()
  const [filter, setFilter] = useState('all')
  const { data, error, loading, reload } = useAsync(
    () => api.evidenceRun(assessmentId, evidenceId), [assessmentId, evidenceId])
  usePageTitle(data ? `Evidence: ${data.host}` : 'Evidence')

  const back = <Link className="back-link" to="/evidence"><Icon name="back" size={16} /> All evidence</Link>
  if (loading && !data) return <div className="page">{back}<Loading /></div>
  if (error) {
    return (
      <div className="page">
        {back}
        <h1 tabIndex={-1} className="h-inline">Collector run</h1>
        <ErrorState error={error} onRetry={reload} />
      </div>
    )
  }

  const unavailable = data.checks.filter((c) => c.status !== 'ok').length
  const shown = data.checks.filter((c) => (filter === 'all' ? true
    : filter === 'unavailable' ? c.status !== 'ok' : c.result === filter))
    .map((c, i) => [c, i])
    .sort(([a, i], [b, j]) => (checkRank(a) - checkRank(b)) || (i - j))
    .map(([c]) => c)
  const collector = COLLECTORS[data.collector] || data.collector

  return (
    <div className="page detail">
      {back}
      <header className="page-head detail-head">
        <div>
          <p className="eyebrow">{collector} collector · format version {data.version}</p>
          <h1 tabIndex={-1} className="break">{data.collector === 'm365' ? `Tenant ${data.host}` : data.host}</h1>
          <div className="chip-row">
            <Chip tone="good" glyph="✓">{data.findings.met} met</Chip>
            <Chip tone="bad" glyph="✕">{data.findings.not_met} not met</Chip>
            <Chip tone="neutral" glyph="–">{data.findings.not_assessed} not assessed by collector</Chip>
            {unavailable > 0 && <Chip tone="warn" glyph="!">{plural(unavailable, 'check')} unavailable</Chip>}
          </div>
        </div>
      </header>

      {data.collector === 'windows' && data.source?.elevated === false && (
        <div className="banner warn" role="note">
          <Icon name="conflict" size={18} />
          <div><strong>Run without administrator rights.</strong> Checks that need elevation were unavailable and decide nothing.</div>
        </div>
      )}

      <div className="detail-grid">
        <section className="detail-main" aria-labelledby="checks-title">
          <div className="section-head">
            <h2 id="checks-title">Checks</h2>
            <label className="field inline-field">
              <span>Show</span>
              <select value={filter} onChange={(e) => setFilter(e.target.value)}>
                {FILTERS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
              </select>
            </label>
          </div>
          <p className="result-count" role="status">
            {plural(shown.length, 'check')} shown of {data.checks.length} · gaps first
          </p>
          {shown.length === 0
            ? <div className="state">No checks match.</div>
            : <ul className="check-list">{shown.map((c) => <CheckCard key={c.id} check={c} />)}</ul>}
        </section>
        <aside className="detail-side" aria-label="About this run">
          <section className="card" aria-labelledby="run-title">
            <h2 id="run-title">This run</h2>
            <dl className="kv compact">
              <div><dt>Collector</dt><dd>{collector}</dd></div>
              <div><dt>Collected</dt><dd>{formatDate(data.collected_at)}</dd></div>
              <div><dt>Uploaded</dt><dd>{formatDate(data.uploaded_at)}</dd></div>
              <div><dt>Checks</dt><dd className="num">{data.checks.length}</dd></div>
            </dl>
          </section>
          <section className="card" aria-labelledby="source-title">
            <h2 id="source-title">{data.collector === 'windows' ? 'Computer' : 'Tenant'}</h2>
            <SourceFacts run={data} />
          </section>
          <section className="card small" aria-labelledby="rule-title">
            <h2 id="rule-title">How findings are used</h2>
            <p className="muted">
              A finding is met or not met only when the check was read and the value understood. Anything else is
              &ldquo;not assessed by collector&rdquo;. The assessor&apos;s answer always wins; a disagreement shows as a
              conflict on the requirement.
            </p>
          </section>
        </aside>
      </div>
    </div>
  )
}
