// All calls to the FastAPI backend live here.
const BASE = (import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000').replace(/\/$/, '')
const KEY = import.meta.env.VITE_API_KEY

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) }
  if (KEY) headers['X-API-Key'] = KEY
  const res = await fetch(`${BASE}${path}`, { ...options, headers })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* keep statusText */ }
    const err = new Error(detail || `HTTP ${res.status}`)
    err.status = res.status
    throw err
  }
  return res.json()
}

export const api = {
  health: () => request('/health'),
  meta: () => request('/meta'),
  listClaims: () => request('/claims'),
  getClaim: (id) => request(`/claims/${id}`),
  getAudit: (id) => request(`/claims/${id}/audit`),
  review: (id, body) =>
    request(`/claims/${id}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  submitClaim: (policyNumber, files) => {
    const form = new FormData()
    form.append('policy_number', policyNumber)
    files.forEach((f) => form.append('files', f, f.name))
    return request('/claims', { method: 'POST', body: form })
  },
}

// Sample claims are plain text files shipped in /public/samples, so the demo works with one click.
export async function listSamples() {
  const res = await fetch('/samples/index.json')
  return res.json()
}

export async function loadSampleFiles(sample) {
  return Promise.all(
    sample.files.map(async (name) => {
      const text = await (await fetch(`/samples/${sample.id}/${name}`)).text()
      return new File([text], name, { type: 'text/plain' })
    }),
  )
}
