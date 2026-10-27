import { useState } from 'react'
import { api } from '../api.js'
import { DECISIONS } from '../labels.js'
import { Card } from './ui.jsx'

const CHOICES = ['APPROVE', 'PARTIAL_APPROVE', 'QUERY_MORE_INFO', 'REJECT']

export default function ReviewPanel({ claim, onDone }) {
  const initial = CHOICES.includes(claim.ai_decision) ? claim.ai_decision : 'QUERY_MORE_INFO'
  const [reviewer, setReviewer] = useState('Claims officer')
  const [decision, setDecision] = useState(initial)
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function send(final_decision) {
    setBusy(true)
    setError('')
    try {
      await api.review(claim.claim_id, { reviewer, final_decision, comment })
      onDone()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card title="Officer decision">
      <label className="field"><span>Your name</span>
        <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
      </label>
      <label className="field"><span>Final decision</span>
        <select value={decision} onChange={(e) => setDecision(e.target.value)}>
          {CHOICES.map((c) => <option key={c} value={c}>{DECISIONS[c].label}</option>)}
        </select>
      </label>
      <label className="field"><span>Comment</span>
        <textarea rows={3} value={comment} onChange={(e) => setComment(e.target.value)} />
      </label>
      <div className="row">
        <button className="btn btn-primary" disabled={busy || !reviewer.trim()} onClick={() => send(decision)}>
          Confirm decision
        </button>
        <button className="btn" disabled={busy || !reviewer.trim()} onClick={() => send('QUERY_MORE_INFO')}>
          Send back to claimant
        </button>
      </div>
      {error && <div className="error" role="alert">{error}</div>}
    </Card>
  )
}
