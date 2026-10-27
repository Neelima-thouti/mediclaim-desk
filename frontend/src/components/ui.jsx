import { DECISIONS, STATUSES, money } from '../labels.js'

export function StatusChip({ status }) {
  const s = STATUSES[status] || { label: status, tone: 'neutral' }
  return <span className={`chip chip-${s.tone}`}>{s.label}</span>
}

export function DecisionBanner({ claim }) {
  const d = DECISIONS[claim.ai_decision]
  if (!d) return null
  return (
    <section className={`banner banner-${d.tone}`} aria-label="Recommendation">
      <div>
        <div className="banner-kicker">AI recommendation</div>
        <div className="banner-title">{d.label}</div>
        <div className="banner-sub">
          Confidence {claim.confidence != null ? Math.round(claim.confidence * 100) : '-'}%
          {claim.human_review_required ? ' · an officer must confirm' : ' · no review needed'}
        </div>
      </div>
      <div className="amounts">
        <div><span>Claimed</span><strong>{money(claim.claimed_amount)}</strong></div>
        <div><span>Payable (computed by code)</span><strong>{money(claim.approved_amount)}</strong></div>
      </div>
    </section>
  )
}

export function Card({ title, children, right }) {
  return (
    <section className="card">
      <div className="card-head"><h3>{title}</h3>{right}</div>
      {children}
    </section>
  )
}
