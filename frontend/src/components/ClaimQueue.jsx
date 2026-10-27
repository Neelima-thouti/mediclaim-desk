import { DECISIONS, money } from '../labels.js'
import { Card, StatusChip } from './ui.jsx'

export default function ClaimQueue({ claims, selectedId, onSelect }) {
  return (
    <Card title="Claim queue">
      {claims.length === 0 && <div className="hint">No claims yet. Submit one above.</div>}
      <ul className="queue">
        {claims.map((c) => (
          <li key={c.claim_id}>
            <button className={`queue-item ${c.claim_id === selectedId ? 'selected' : ''}`} onClick={() => onSelect(c.claim_id)}>
              <div className="queue-top">
                <code>{c.claim_id}</code>
                <StatusChip status={c.status} />
              </div>
              <div className="queue-sub">
                {c.ai_decision ? (DECISIONS[c.ai_decision]?.label || c.ai_decision) : 'Working...'} · {money(c.claimed_amount)}
              </div>
            </button>
          </li>
        ))}
      </ul>
    </Card>
  )
}
