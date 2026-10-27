import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import ClaimDetail from './components/ClaimDetail.jsx'
import ClaimQueue from './components/ClaimQueue.jsx'
import NewClaim from './components/NewClaim.jsx'

export default function App() {
  const [claims, setClaims] = useState([])
  const [selected, setSelected] = useState(null)
  const [meta, setMeta] = useState(null)
  const [apiDown, setApiDown] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setClaims(await api.listClaims())
      setApiDown(false)
    } catch {
      setApiDown(true)
    }
  }, [])

  useEffect(() => {
    api.meta().then(setMeta).catch(() => {})
    refresh()
    const id = setInterval(refresh, 3000)
    return () => clearInterval(id)
  }, [refresh])

  const created = (id) => { setSelected(id); refresh() }

  return (
    <div className="app">
      <header className="top">
        <div>
          <h1>Mediclaim Desk</h1>
          <p>AI-assisted validation of health insurance reimbursement claims. Synthetic data only. Not for real claim decisions.</p>
        </div>
        <div className="badges" aria-label="Environment">
          {apiDown && <span className="chip chip-bad">API not reachable</span>}
          {meta && (
            <>
              <span className="chip chip-neutral">Workflow: {meta.engine}</span>
              <span className="chip chip-neutral">Model: {meta.llm_provider === 'mock' ? 'offline mock' : (meta.model || meta.llm_provider)}</span>
              <span className="chip chip-neutral">SQL: {meta.sql}</span>
              <span className="chip chip-neutral">Audit: {meta.audit_store}</span>
            </>
          )}
        </div>
      </header>

      <main className="layout">
        <aside>
          <NewClaim onCreated={created} />
          <ClaimQueue claims={claims} selectedId={selected} onSelect={setSelected} />
        </aside>
        <section>
          {selected ? (
            <ClaimDetail key={selected} claimId={selected} onChanged={refresh} />
          ) : (
            <div className="empty">
              <h2>Start a demo</h2>
              <p>Click one of the one-click demo claims on the left. Try the clean claim first, then the suspicious one.</p>
            </div>
          )}
        </section>
      </main>
    </div>
  )
}
