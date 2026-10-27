import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App.jsx'

const CLAIM_ID = 'CLM-ABC123'

const listRow = {
  claim_id: CLAIM_ID, policy_number: 'POL-123456', status: 'AWAITING_REVIEW', ai_decision: 'ESCALATE_TO_HUMAN',
  final_decision: null, claimed_amount: 150000, approved_amount: 0, human_review_required: true, created_at: '2026-10-23T10:00:00Z',
}
const claim = {
  ...listRow, confidence: 0.9, error: null,
  documents: [{ filename: 'hospital_bill.txt', doc_type: 'HOSPITAL_BILL' }],
  findings: [
    { agent: 'rules', severity: 'BLOCKER', code: 'DUPLICATE_BILL', message: 'Bill B-77821 was already claimed', evidence: 'earlier amount 150000' },
    { agent: 'rules', severity: 'WARN', code: 'LATE_SUBMISSION', message: 'Claim filed 35 days after discharge', evidence: null },
  ],
  reviews: [],
}
const audit = {
  engine: 'langgraph',
  trace: [
    { step: 'classify', status: 'done', seconds: 0.1, note: '3 documents typed' },
    { step: 'rules', status: 'done', seconds: 0.2, note: '4 rule findings; payable 0' },
    { step: 'human_review', status: 'waiting', seconds: 0, note: 'paused for the officer' },
  ],
  payable_breakdown: { claimed: 150000, approved: 0, deductions: [] },
}

let calls
function mockFetch() {
  calls = []
  globalThis.fetch = vi.fn(async (url, options = {}) => {
    const path = String(url).replace('http://127.0.0.1:8000', '')
    calls.push({ path, method: options.method || 'GET', body: options.body })
    const json = (data) => ({ ok: true, status: 200, json: async () => data, text: async () => '' })
    if (path === '/health') return json({ status: 'ok' })
    if (path === '/meta') return json({ engine: 'langgraph', llm_provider: 'mock', model: null, sql: 'sqlite', audit_store: 'local-files' })
    if (path === '/claims' && !options.method) return json([listRow])
    if (path === `/claims/${CLAIM_ID}` && !options.method) return json(claim)
    if (path === `/claims/${CLAIM_ID}/audit`) return json(audit)
    if (path === `/claims/${CLAIM_ID}/review`) return json({ ...claim, status: 'COMPLETED', final_decision: 'QUERY_MORE_INFO' })
    if (path === '/claims' && options.method === 'POST') return json({ claim_id: CLAIM_ID, status: 'RECEIVED' })
    if (path === '/samples/index.json') return json([{ id: 'claim_001_clean', title: 'Clean claim (appendicitis)', blurb: 'x', files: ['claim_form.txt'] }])
    if (path.startsWith('/samples/')) return { ok: true, status: 200, text: async () => 'CLAIM FORM', json: async () => ({}) }
    return { ok: false, status: 404, statusText: 'Not found', json: async () => ({ detail: 'nope' }) }
  })
}

beforeEach(mockFetch)
afterEach(() => vi.restoreAllMocks())

describe('Mediclaim Desk', () => {
  it('shows environment badges and the claim queue', async () => {
    render(<App />)
    expect(await screen.findByText('Workflow: langgraph')).toBeInTheDocument()
    expect(screen.getByText('Model: offline mock')).toBeInTheDocument()
    const queue = await screen.findByRole('button', { name: new RegExp(CLAIM_ID) })
    expect(within(queue).getByText('Awaiting review')).toBeInTheDocument()
  })

  it('shows the recommendation, trace, findings and sends the claim back', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: new RegExp(CLAIM_ID) }))

    expect(await screen.findByText('Escalate to officer')).toBeInTheDocument()
    expect(screen.getByText('DUPLICATE_BILL')).toBeInTheDocument()
    expect(screen.getByText('Bill B-77821 was already claimed')).toBeInTheDocument()
    expect(await screen.findByText('Officer review')).toBeInTheDocument()
    expect(screen.getByText('Rules engine')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Send back to claimant' }))
    await waitFor(() => expect(calls.some((c) => c.path.endsWith('/review') && c.method === 'POST')).toBe(true))
    const post = calls.find((c) => c.path.endsWith('/review'))
    expect(JSON.parse(post.body)).toMatchObject({ final_decision: 'QUERY_MORE_INFO', reviewer: 'Claims officer' })
  })

  it('submits a one-click sample claim and opens it', async () => {
    const user = userEvent.setup()
    render(<App />)
    await user.click(await screen.findByRole('button', { name: 'Clean claim (appendicitis)' }))
    await waitFor(() => expect(calls.some((c) => c.path === '/claims' && c.method === 'POST')).toBe(true))
    expect(await screen.findByText('Escalate to officer')).toBeInTheDocument()
  })

  it('warns when the API is not reachable', async () => {
    globalThis.fetch = vi.fn(async () => { throw new Error('network down') })
    render(<App />)
    expect(await screen.findByText('API not reachable')).toBeInTheDocument()
  })
})
