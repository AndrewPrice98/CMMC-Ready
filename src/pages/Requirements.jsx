import { useEffect, useMemo, useState } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import {
  Empty, ErrorState, FAMILIES, Icon, Loading, STATUS_OPTIONS, StatusChip, cmmcId, plural, useAsync,
  usePageTitle, useSession,
} from '../components/ui.jsx'

const FAMILY_CODES = new Set(FAMILIES.map((f) => f.code))
const STATUS_CODES = new Set(STATUS_OPTIONS.map(([v]) => v))

/** Read filters from the URL, dropping anything that isn't on the allow-lists. */
function readFilters(params) {
  const family = params.get('family') || ''
  const status = params.get('status') || ''
  return {
    family: FAMILY_CODES.has(family) ? family : '',
    status: STATUS_CODES.has(status) ? status : '',
    q: (params.get('q') || '').slice(0, 200),
    conflicts: params.get('conflicts') === '1',
  }
}

function PointsCell({ item }) {
  if (item.points_lost > 0) {
    return (
      <span className="pts lost">
        <span aria-hidden="true">−{item.points_lost}</span>
        <span className="sr-only">{plural(item.points_lost, 'point')} lost</span>
      </span>
    )
  }
  return (
    <span className="pts">
      <span aria-hidden="true">{item.weight}</span>
      <span className="sr-only">weight {item.weight}, none lost</span>
    </span>
  )
}

function EvidenceCell({ item }) {
  if (!item.evidence) {
    return <span className="muted"><span aria-hidden="true">—</span><span className="sr-only">None</span></span>
  }
  return (
    <span className="evidence-cell">
      <span className="ev" title={`Automated evidence for ${plural(item.evidence, 'objective')}`}>
        <Icon name="evidence" size={16} />
        <span className="num">{item.evidence}</span>
        <span className="sr-only"> {item.evidence === 1 ? 'objective has' : 'objectives have'} automated evidence</span>
      </span>
      {item.conflicts > 0 && (
        <span className="ev conflict" title={`${plural(item.conflicts, 'objective')} conflict with evidence`}>
          <Icon name="conflict" size={16} />
          <span className="num">{item.conflicts}</span>
          <span className="sr-only"> {item.conflicts === 1 ? 'conflict' : 'conflicts'} with evidence</span>
        </span>
      )}
    </span>
  )
}

export default function Requirements() {
  usePageTitle('Requirements')
  const { assessmentId } = useSession()
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const filters = readFilters(params)
  const [search, setSearch] = useState(filters.q)

  // Keep the text box in step when the URL changes (back/forward, heatmap links).
  useEffect(() => { setSearch(filters.q) }, [filters.q])

  function update(changes) {
    const next = { ...filters, ...changes }
    const sp = new URLSearchParams()
    if (next.family) sp.set('family', next.family)
    if (next.status) sp.set('status', next.status)
    if (next.q) sp.set('q', next.q)
    if (next.conflicts) sp.set('conflicts', '1')
    setParams(sp, { replace: true })
  }

  // Debounce typing into the search box.
  useEffect(() => {
    const value = search.trim()
    if (value === filters.q) return undefined
    const t = setTimeout(() => update({ q: value }), 250)
    return () => clearTimeout(t)
  }, [search]) // eslint-disable-line react-hooks/exhaustive-deps

  const { data, error, loading, reload } = useAsync(
    () => api.requirements(assessmentId, { family: filters.family, status: filters.status, q: filters.q }),
    [assessmentId, filters.family, filters.status, filters.q],
  )

  const items = useMemo(
    () => (data ? data.items.filter((i) => !filters.conflicts || i.conflicts > 0) : []),
    [data, filters.conflicts],
  )
  const anyFilter = filters.family || filters.status || filters.q || filters.conflicts

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <p className="eyebrow">NIST SP 800-171 Rev 2</p>
          <h1 tabIndex={-1}>Requirements</h1>
          <p className="muted">110 requirements in 14 families, assessed through 320 objectives.</p>
        </div>
      </header>

      <form className="filters card" role="search" onSubmit={(e) => { e.preventDefault(); update({ q: search.trim() }) }}>
        <label className="field grow">
          <span>Search</span>
          <input type="search" value={search} maxLength={200} placeholder="ID or requirement text"
            onChange={(e) => setSearch(e.target.value)} />
        </label>
        <label className="field">
          <span>Family</span>
          <select value={filters.family} onChange={(e) => update({ family: e.target.value })}>
            <option value="">All families</option>
            {FAMILIES.map((f) => <option key={f.code} value={f.code}>{f.code} · {f.name}</option>)}
          </select>
        </label>
        <label className="field">
          <span>Status</span>
          <select value={filters.status} onChange={(e) => update({ status: e.target.value })}>
            <option value="">All statuses</option>
            {STATUS_OPTIONS.map(([v, label]) => <option key={v} value={v}>{label}</option>)}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={filters.conflicts} onChange={(e) => update({ conflicts: e.target.checked })} />
          <span>Only conflicts with evidence</span>
        </label>
        {anyFilter && (
          <button type="button" className="btn ghost small" onClick={() => { setSearch(''); setParams({}, { replace: true }) }}>
            Clear filters
          </button>
        )}
      </form>

      <p className="result-count">
        <span role="status" aria-live="polite">{data ? `${plural(items.length, 'requirement')} shown` : ''}</span>
        <span> · Points: −N is the deduction applied; otherwise the requirement&apos;s weight.</span>
      </p>

      {error && <ErrorState error={error} onRetry={reload} />}
      {loading && !data && <Loading />}
      {data && items.length === 0 && <Empty>No requirements match these filters.</Empty>}
      {data && items.length > 0 && (
        <div className="table-wrap card flush" aria-busy={loading}>
          <table className="table req-table">
            <caption className="sr-only">
              Requirements with status, points and automated evidence. Points show the deduction applied, or the weight when nothing is lost.
            </caption>
            <thead>
              <tr>
                <th scope="col">ID</th>
                <th scope="col">Requirement</th>
                <th scope="col">Status</th>
                <th scope="col" className="right" title="Points lost (−) or the requirement's weight">Points</th>
                <th scope="col">Evidence</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td className="id-cell">
                    <Link to={`/requirements/${item.id}`} state={{ from: location.search }} className="req-link">
                      <span className="id-text strong">{item.id}</span>
                      <span className="cmmc-id">{cmmcId(item.id)}</span>
                    </Link>
                  </td>
                  <td className="text-cell"><span className="clamp">{item.text}</span></td>
                  <td className="status-cell"><StatusChip status={item.status} /></td>
                  <td className="right points-cell" data-label="Points"><PointsCell item={item} /></td>
                  <td className="evidence-td" data-label="Evidence"><EvidenceCell item={item} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
