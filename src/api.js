// Thin wrapper around the CMMC Ready REST API.
//
// Authentication uses an httpOnly session cookie that the browser sends automatically
// with same-origin requests, so no token is ever handled in JavaScript. Any 401 fires
// a "cmmcready:unauthorized" event and the app returns to the sign-in screen.

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

async function request(path, options = {}) {
  let res
  try {
    res = await fetch(`/api${path}`, { credentials: 'same-origin', ...options })
  } catch {
    throw new ApiError('Cannot reach the CMMC Ready API.', 0)
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body.detail) {
        detail = typeof body.detail === 'string'
          ? body.detail
          : body.detail.map?.((d) => d.msg).join('; ') || JSON.stringify(body.detail)
      }
    } catch { /* not JSON */ }
    if (res.status === 401 && !path.startsWith('/auth/')) {
      window.dispatchEvent(new Event('cmmcready:unauthorized'))
    }
    throw new ApiError(detail, res.status)
  }
  return res.json()
}

const send = (method, body) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export function qs(params) {
  const sp = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    sp.append(key, value)
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

const enc = encodeURIComponent
const assessment = (id) => `/assessments/${enc(id)}`

export const api = {
  health: () => request('/health'),
  me: () => request('/auth/me'),
  login: (username, password) => request('/auth/login', send('POST', { username, password })),
  logout: () => request('/auth/logout', { method: 'POST' }),

  organization: () => request('/organization'),
  assessments: () => request('/assessments'),
  overview: (id) => request(`${assessment(id)}/overview`),
  requirements: (id, params = {}) => request(`${assessment(id)}/requirements${qs(params)}`),
  requirement: (id, reqId) => request(`${assessment(id)}/requirements/${enc(reqId)}`),

  assets: () => request('/assets'),
  evidence: (id) => request(`${assessment(id)}/evidence`),
  evidenceRun: (id, evidenceId) => request(`${assessment(id)}/evidence/${enc(evidenceId)}`),
  poam: (id) => request(`${assessment(id)}/poam`),
  sprs: (id) => request(`${assessment(id)}/sprs`),
  history: () => request('/history'),
  /** Same-origin download link; the session cookie goes with it. */
  exportUrl: (id, name) => `/api${assessment(id)}/exports/${name}`,

  // Writer-only routes; the server answers 403 for guests.
  answer: (id, objectiveId, body) => request(`${assessment(id)}/objectives/${enc(objectiveId)}`, send('PUT', body)),
  partial: (id, reqId, choice) => request(`${assessment(id)}/partial/${enc(reqId)}`, send('PUT', { choice })),
  odp: (id, values) => request(`${assessment(id)}/odp`, send('PUT', values)),
  saveOrganization: (body) => request('/organization', send('PUT', body)),
  createAsset: (body) => request('/assets', send('POST', body)),
  updateAsset: (assetId, body) => request(`/assets/${enc(assetId)}`, send('PUT', body)),
  deleteAsset: (assetId) => request(`/assets/${enc(assetId)}`, { method: 'DELETE' }),
  createAssessment: (body) => request('/assessments', send('POST', body)),
  updateAssessment: (id, body) => request(assessment(id), send('PATCH', body)),
  uploadEvidence: (id, file) => {
    const form = new FormData()
    form.append('file', file)
    return request(`${assessment(id)}/evidence`, { method: 'POST', body: form })
  },
  createPoam: (id, body) => request(`${assessment(id)}/poam`, send('POST', body)),
  updatePoam: (id, itemId, body) => request(`${assessment(id)}/poam/${enc(itemId)}`, send('PATCH', body)),
}
