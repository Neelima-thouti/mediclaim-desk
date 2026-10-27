import { Card } from './ui.jsx'

const ORDER = ['BLOCKER', 'WARN', 'INFO']

export default function Findings({ findings }) {
  const sorted = [...findings].sort((a, b) => ORDER.indexOf(a.severity) - ORDER.indexOf(b.severity))
  return (
    <Card title={`Findings (${findings.length})`}>
      {sorted.length === 0 && <div className="hint">No problems found.</div>}
      <ul className="findings">
        {sorted.map((f, i) => (
          <li key={i} className={`finding finding-${f.severity}`}>
            <div className="finding-top">
              <span className="sev">{f.severity}</span>
              <code>{f.code}</code>
              <span className="agent">{f.agent}</span>
            </div>
            <div>{f.message}</div>
            {f.evidence && <div className="evidence">Evidence: {f.evidence}</div>}
          </li>
        ))}
      </ul>
    </Card>
  )
}
