import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api.js'
import {
  COLLECTORS, CommandBlock, Empty, ErrorState, GITHUB_URL, Icon, Loading, formatDate, plural, useAsync,
  usePageTitle, useSession,
} from '../components/ui.jsx'

// The exact commands, with the parameter names from collectors/collect-windows.ps1 and
// collectors/collect-m365.ps1 (-OutFile, -RedactNames, -AuditWindowDays).
const WINDOWS_RUN = 'powershell -ExecutionPolicy Bypass -File .\\collect-windows.ps1 -OutFile windows-evidence.json'
const WINDOWS_REDACT = 'powershell -ExecutionPolicy Bypass -File .\\collect-windows.ps1 -OutFile windows-evidence.json -RedactNames'
const M365_MODULE = 'Install-Module Microsoft.Graph.Authentication -Scope CurrentUser'
const M365_RUN = 'powershell -ExecutionPolicy Bypass -File .\\collect-m365.ps1 -OutFile m365-evidence.json -RedactNames'
const M365_WINDOW = 'powershell -ExecutionPolicy Bypass -File .\\collect-m365.ps1 -OutFile m365-evidence.json -RedactNames -AuditWindowDays 30'
const COLLECTORS_URL = `${GITHUB_URL}/tree/main/collectors`

function Counts({ findings }) {
  return (
    <>
      <td className="right num count-cell good-text" data-label="Met">{findings.met}</td>
      <td className="right num count-cell bad-text" data-label="Not met">{findings.not_met}</td>
      <td className="right num count-cell" data-label="Not assessed">{findings.not_assessed}</td>
    </>
  )
}

function RunsTable({ runs }) {
  return (
    <div className="table-wrap card flush">
      <table className="table runs-table">
        <caption className="sr-only">
          Collector runs, with how many objective findings each produced: met, not met and not assessed by the collector.
        </caption>
        <thead>
          <tr>
            <th scope="col">Host or tenant</th>
            <th scope="col">Collector</th>
            <th scope="col">Collected</th>
            <th scope="col">Uploaded</th>
            <th scope="col" className="right">Met</th>
            <th scope="col" className="right">Not met</th>
            <th scope="col" className="right">Not assessed</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td className="host-cell">
                <Link to={`/evidence/${run.id}`} className="req-link">
                  <span className="strong break">{run.host}</span>
                  <span className="cmmc-id">View checks and commands</span>
                </Link>
              </td>
              <td className="collector-cell">
                <span className="collector-tag"><Icon name={run.collector === 'm365' ? 'shield' : 'terminal'} size={15} />
                  {COLLECTORS[run.collector] || run.collector}</span>
              </td>
              <td className="date-cell" data-label="Collected">{formatDate(run.collected_at)}</td>
              <td className="date-cell" data-label="Uploaded">{formatDate(run.uploaded_at)}</td>
              <Counts findings={run.findings} />
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Explain an upload error by its status code; the server's message says what exactly. */
function uploadError(err) {
  const lead = {
    400: 'This is not CMMC Ready collector output.',
    403: 'Only an admin can upload evidence.',
    413: 'The file is too large.',
    415: 'The file is not readable text.',
  }[err.status]
  return lead ? `${lead} ${err.message}` : err.message
}

function UploadCard({ assessmentId, onUploaded }) {
  const input = useRef(null)
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  async function upload(e) {
    e.preventDefault()
    if (!file || busy) return
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const run = await api.uploadEvidence(assessmentId, file)
      const counts = { met: 0, not_met: 0, not_assessed: 0 }
      for (const f of run.findings) counts[f.result] += 1
      setResult({ ...run, counts })
      setFile(null)
      if (input.current) input.current.value = ''
      onUploaded()
    } catch (err) {
      setError(uploadError(err))
    }
    setBusy(false)
  }

  return (
    <section className="card upload-card" aria-labelledby="upload-title">
      <h2 id="upload-title">Upload collector output</h2>
      <p className="muted small">
        The JSON file a collector wrote. It is checked, stored with this assessment and turned into objective
        findings at once. Findings inform the assessor; they never change an answer.
      </p>
      <form onSubmit={upload} className="upload-form">
        <label className="field">
          <span>Collector file (.json)</span>
          <input ref={input} type="file" accept=".json,application/json" className="file-input"
            onChange={(e) => { setFile(e.target.files?.[0] || null); setError(null); setResult(null) }} />
        </label>
        <div className="form-actions">
          <button className="btn primary small" aria-disabled={!file || busy ? 'true' : undefined}>
            <Icon name="upload" size={15} /> {busy ? 'Uploading…' : 'Upload'}
          </button>
          <span role="status" className="form-msg ok">
            {result && `Uploaded ${result.host}: ${result.counts.met} met, ${result.counts.not_met} not met, `
              + `${result.counts.not_assessed} not assessed.`}
          </span>
        </div>
      </form>
      {error && <div className="state error upload-error" role="alert"><strong>Upload refused.</strong> {error}</div>}
      {result && (
        <Link className="btn secondary small" to={`/evidence/${result.id}`}>
          View the checks <Icon name="arrow" size={15} />
        </Link>
      )}
    </section>
  )
}

function HowTo({ guest }) {
  return (
    <section className="card howto" aria-labelledby="howto-title">
      <div className="card-head">
        <h2 id="howto-title">How to run the collectors</h2>
        <a href={COLLECTORS_URL} target="_blank" rel="noreferrer" className="small">
          Scripts on GitHub<span className="sr-only"> (opens in a new tab)</span> <Icon name="external" size={14} />
        </a>
      </div>
      <p className="muted small">
        Both collectors are read-only PowerShell scripts. They never change a setting, never ask the app for credentials,
        and record the exact command behind every check. A check they cannot read is marked unavailable and decides nothing.
      </p>
      <div className="howto-grid">
        <div className="howto-col">
          <h3><Icon name="terminal" size={16} /> Windows computer</h3>
          <ol className="howto-steps">
            <li>Download <code>collect-windows.ps1</code> and open PowerShell <strong>as administrator</strong> in that folder.</li>
            <li>
              Run the collector:
              <CommandBlock command={WINDOWS_RUN} what="Windows collector command" />
            </li>
            <li>
              To replace the names of local Administrators members with member-1, member-2…, add <code>-RedactNames</code>:
              <CommandBlock command={WINDOWS_REDACT} what="Windows collector command with redaction" />
            </li>
          </ol>
          <p className="small muted">Works on Windows PowerShell 5.1 and PowerShell 7. Without administrator rights some checks are unavailable.</p>
        </div>
        <div className="howto-col">
          <h3><Icon name="shield" size={16} /> Microsoft 365 / Entra ID tenant</h3>
          <ol className="howto-steps">
            <li>
              Install the Microsoft Graph sign-in module once:
              <CommandBlock command={M365_MODULE} what="Graph module install command" />
            </li>
            <li>
              Run the collector and sign in when asked:
              <CommandBlock command={M365_RUN} what="Microsoft 365 collector command" />
            </li>
            <li>
              Audit entries cover 7 days by default; <code>-AuditWindowDays</code> takes 1 to 30:
              <CommandBlock command={M365_WINDOW} what="Microsoft 365 collector command with a 30-day audit window" />
            </li>
          </ol>
          <p className="small muted">
            The sign-in asks for four read-only scopes: <code>Policy.Read.All</code>, <code>Directory.Read.All</code>,{' '}
            <code>AuditLog.Read.All</code> and <code>RoleManagement.Read.Directory</code>. A Global Reader or Security
            Reader account is enough. <code>-RedactNames</code> leaves out role members&apos; names.
          </p>
        </div>
      </div>
      <p className="small howto-last">
        <strong>Then</strong> {guest ? 'an admin uploads the JSON file it wrote on this page.' : 'upload the JSON file it wrote with the form on this page.'}
      </p>
    </section>
  )
}

export default function Evidence() {
  usePageTitle('Evidence')
  const { assessmentId, assessments, guest } = useSession()
  const { data, error, loading, reload } = useAsync(() => api.evidence(assessmentId), [assessmentId])
  const assessment = assessments.find((a) => a.id === assessmentId)
  const totals = (data || []).reduce((acc, r) => {
    for (const k of ['met', 'not_met', 'not_assessed']) acc[k] += r.findings[k]
    return acc
  }, { met: 0, not_met: 0, not_assessed: 0 })

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">Automated evidence</p>
          <h1 tabIndex={-1}>Evidence</h1>
          <p className="muted">
            Collector runs for {assessment?.title || 'this assessment'}. Findings inform objectives; the
            assessor&apos;s answer always decides the score.
          </p>
        </div>
      </header>

      {error && <ErrorState error={error} onRetry={reload} />}
      {loading && !data && <Loading />}
      {data && (
        <section aria-labelledby="runs-title" className="section">
          <div className="section-head">
            <h2 id="runs-title">Collector runs</h2>
            {data.length > 0 && (
              <p className="muted small">
                {plural(data.length, 'run')} · {totals.met} met · {totals.not_met} not met · {totals.not_assessed} not assessed by collector
              </p>
            )}
          </div>
          {data.length === 0 ? (
            <Empty>
              No collector output yet.{' '}
              {guest ? 'An admin uploads it after running a collector.' : 'Run a collector as shown below, then upload its JSON file.'}
            </Empty>
          ) : <RunsTable runs={data} />}
        </section>
      )}

      <div className={guest ? 'evidence-grid single' : 'evidence-grid'}>
        <HowTo guest={guest} />
        {!guest && <UploadCard assessmentId={assessmentId} onUploaded={reload} />}
      </div>
    </div>
  )
}
