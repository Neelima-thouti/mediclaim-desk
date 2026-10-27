import { BY, STEPS } from '../labels.js'
import { Card } from './ui.jsx'

export default function Pipeline({ audit }) {
  const trace = audit?.trace || []
  return (
    <Card
      title="Workflow trace"
      right={<span className="hint">{audit?.engine === 'langgraph' ? 'LangGraph' : audit?.engine || ''}</span>}
    >
      {trace.length === 0 ? (
        <div className="hint">No step trace for this engine.</div>
      ) : (
        <ol className="trace">
          {trace.map((t, i) => {
            const meta = STEPS[t.step] || { label: t.step, by: 'code' }
            return (
              <li key={i} className={`trace-${t.status}`}>
                <span className="trace-icon" aria-hidden>{t.status === 'waiting' ? '⏸' : '✓'}</span>
                <div className="trace-body">
                  <div>
                    <strong>{meta.label}</strong>
                    <span className={`by by-${meta.by}`}>{BY[meta.by]}</span>
                  </div>
                  <div className="trace-note">{t.note}{t.status === 'done' && t.seconds ? ` · ${t.seconds}s` : ''}</div>
                </div>
              </li>
            )
          })}
        </ol>
      )}
      <div className="legend">
        <span className="by by-ai">AI model</span> reads and judges ·{' '}
        <span className="by by-code">Plain code</span> calculates and enforces ·{' '}
        <span className="by by-person">Person</span> decides
      </div>
    </Card>
  )
}
