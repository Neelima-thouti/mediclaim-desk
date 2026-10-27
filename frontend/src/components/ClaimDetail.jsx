import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { DECISIONS, money } from '../labels.js'
import Findings from './Findings.jsx'
import Pipeline from './Pipeline.jsx'
import ReviewPanel from './ReviewPanel.jsx'
import { Card, DecisionBanner, StatusChip } from './ui.jsx'

const WORKING = ['RECEIVED', 'PROCESSING']

export default function ClaimDetail({ claimId, onChanged }) {
  const [claim, setClaim] = useState(null)
  const [audit, setAudit] = useState(null)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const c = await api.getClaim(claimId)
      setClaim(c)
      setError('')
      if (!WORKING.includes(c.status) && c.status !== 'FAILED') {
        try { setAudit(await api.getAudit(claimId)) } catch { setAudit(null) }
      }
      return c
    } catch (e) {
      setError(e.message)
      return null
    }
  }, [claimId])

  useEffect(() => {
    setClaim(null)
    setAudit(null)
    let timer
    let stopped = false
    const tick = async () => {
      const c = await load()
      if (!stopped && (!c || WORKING.includes(c.status))) timer = setTimeout(tick, 1500)
    }
    tick()
    return () => { stopped = true; clearTimeout(timer) }
  }, [load])

  if (error && !claim) return <div className="error" role="alert">{error}</div>
  if (!claim) return <div className="hint">Loading claim...</div>

  const done = () => { load(); onChanged() }
  const payable = audit?.payable_breakdown

  return (
    <div className="detail">
      <div className="detail-head">
        <h2><code>{claim.claim_id}</code></h2>
        <StatusChip status={claim.status} />
        {claim.final_decision && (
          <span className="final">Final: <strong>{DECISIONS[claim.final_decision]?.label || claim.final_decision}</strong></span>
        )}
      </div>

      {WORKING.includes(claim.status) && <div className="hint">The workflow is running. This page updates by itself.</div>}
      {claim.status === 'FAILED' && <div className="error" role="alert">Processing failed: {claim.error}</div>}
      {claim.ai_decision && <DecisionBanner claim={claim} />}

      {claim.status === 'AWAITING_REVIEW' && <ReviewPanel claim={claim} onDone={done} />}

      {audit && <Pipeline audit={audit} />}
      {claim.ai_decision && <Findings findings={claim.findings} />}

      {payable && payable.deductions && (
        <Card title="How the payable amount was calculated">
          <table className="table">
            <tbody>
              <tr><td>Claimed</td><td>{money(payable.claimed)}</td></tr>
              {payable.deductions.map((d, i) => (
                <tr key={i}><td>{d.item}<div className="hint">{d.reason}</div></td><td>- {money(d.amount)}</td></tr>
              ))}
              <tr className="total"><td>Payable</td><td>{money(payable.approved)}</td></tr>
            </tbody>
          </table>
          <div className="hint">Amounts come from plain code, never from the AI model.</div>
        </Card>
      )}

      <Card title={`Documents (${claim.documents.length})`}>
        <ul className="docs">
          {claim.documents.map((d) => (
            <li key={d.filename}><code>{d.filename}</code><span className="tag">{d.doc_type || 'pending'}</span></li>
          ))}
        </ul>
      </Card>

      {claim.reviews.length > 0 && (
        <Card title="Review history">
          <ul className="docs">
            {claim.reviews.map((r, i) => (
              <li key={i}><strong>{r.reviewer}</strong> chose {DECISIONS[r.final_decision]?.label || r.final_decision}
                {r.comment ? `: ${r.comment}` : ''}</li>
            ))}
          </ul>
        </Card>
      )}

      {audit && (
        <details className="card audit">
          <summary>Full audit record (stored in Cosmos DB or local files)</summary>
          <pre>{JSON.stringify(audit, null, 2)}</pre>
        </details>
      )}
    </div>
  )
}
