import { api } from '../api.js'
import {
  Chip, DISCLAIMER, ErrorState, Icon, Loading, MAX_SCORE, formatDate, useAsync, usePageTitle, useSession,
} from '../components/ui.jsx'

const EXPORTS = [
  {
    file: 'ssp.docx', title: 'System Security Plan', format: 'Word (.docx)',
    text: 'The organization and CUI boundary, the asset inventory by category, the status of all 110 requirements and the organization-defined parameters.',
  },
  {
    file: 'poam.docx', title: 'POA&M', format: 'Word (.docx)',
    text: 'Every plan of action item with its weakness, remediation, owner, milestones, due date and status.',
  },
  {
    file: 'poam.csv', title: 'POA&M', format: 'Spreadsheet (.csv)',
    text: 'The same POA&M items as rows, for tracking in a spreadsheet. Formula characters are neutralised.',
  },
  {
    file: 'sprs.md', title: 'SPRS summary', format: 'Markdown (.md)',
    text: 'The values to enter in the Supplier Performance Risk System, shown below as well.',
  },
]

function SprsSummary({ s }) {
  const cage = Array.isArray(s.scope.cage_codes) ? s.scope.cage_codes.join(', ') : s.scope.cage_codes
  return (
    <section className="panel sprs-card" aria-labelledby="sprs-title">
      <div className="panel-head">
        <h2 id="sprs-title">SPRS summary</h2>
        {s.provisional && <Chip tone="warn">Provisional</Chip>}
      </div>
      <div className="panel-body">
        <p className="muted small">The values to enter in SPRS for this self-assessment, exactly as in the Markdown export.</p>
        {s.provisional_note && (
          <div className="notice warn" role="note">
            <Icon name="conflict" size={16} />
            <p><strong>Not ready to submit.</strong> {s.provisional_note}</p>
          </div>
        )}
        <dl className="kv sprs-kv">
          <div><dt>Assessment date</dt><dd>{formatDate(s.assessment_date)}</dd></div>
          <div>
            <dt>SPRS score</dt>
            <dd><span className="sprs-score num">{s.score < 0 ? `−${Math.abs(s.score)}` : s.score}</span>
              <span className="muted"> of {s.max_score ?? MAX_SCORE}</span></dd>
          </div>
          <div><dt>Scope</dt><dd className="break">{s.scope.organization}</dd></div>
          <div><dt>CAGE code(s)</dt><dd>{cage || 'None recorded'}</dd></div>
          <div><dt>System Security Plan</dt><dd className="break">{s.ssp_name}</dd></div>
          <div><dt>SSP version</dt><dd>{s.ssp_version}</dd></div>
          <div>
            <dt>Planned POA&amp;M completion date</dt>
            <dd>{s.poam_completion_date && s.poam_completion_date !== 'None' ? formatDate(s.poam_completion_date) : 'None'}</dd>
          </div>
        </dl>
      </div>
    </section>
  )
}

export default function Documents() {
  usePageTitle('Documents')
  const { assessmentId, assessments } = useSession()
  const assessment = assessments.find((a) => a.id === assessmentId)
  const { data, error, loading, reload } = useAsync(() => api.sprs(assessmentId), [assessmentId])

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1 tabIndex={-1}>Documents</h1>
          <p className="page-sub">
            Generated from {assessment?.title || 'this assessment'} when you download them, so they always match what
            the dashboard shows.
          </p>
        </div>
      </header>

      <div className="notice info" role="note">
        <Icon name="info" size={16} />
        <p><strong>Every export opens with this disclaimer.</strong> {DISCLAIMER}</p>
      </div>

      <div className="stack">
        <section className="panel" aria-labelledby="exports-title">
          <div className="panel-head"><h2 id="exports-title">Exports</h2></div>
          <ul className="doc-list">
            {EXPORTS.map((x) => (
              <li key={x.file} className="doc-row">
                <span className="doc-icon" aria-hidden="true"><Icon name="file" size={18} /></span>
                <div className="doc-main">
                  <h3>{x.title} <span className="doc-format">{x.format}</span></h3>
                  <p className="muted small">{x.text}</p>
                </div>
                <a className="btn secondary small" href={api.exportUrl(assessmentId, x.file)} download>
                  <Icon name="download" size={14} /> Download<span className="sr-only"> {x.title}, {x.format}</span>
                </a>
              </li>
            ))}
          </ul>
        </section>

        {error && <ErrorState error={error} onRetry={reload} />}
        {loading && !data && <Loading />}
        {data && <SprsSummary s={data} />}
      </div>
    </div>
  )
}
