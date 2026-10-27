import { useEffect, useState } from 'react'
import { api, listSamples, loadSampleFiles } from '../api.js'
import { Card } from './ui.jsx'

export default function NewClaim({ onCreated }) {
  const [policy, setPolicy] = useState('POL-123456')
  const [files, setFiles] = useState([])
  const [samples, setSamples] = useState([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    listSamples().then(setSamples).catch(() => setSamples([]))
  }, [])

  async function submit(fileList) {
    setBusy(true)
    setError('')
    try {
      const res = await api.submitClaim(policy, fileList)
      setFiles([])
      onCreated(res.claim_id)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function useSample(sample) {
    try {
      submit(await loadSampleFiles(sample))
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <Card title="New claim">
      <label className="field">
        <span>Policy number</span>
        <input value={policy} onChange={(e) => setPolicy(e.target.value)} />
      </label>

      <div className="samples">
        <span className="hint">One-click demo claims (fake data):</span>
        {samples.map((s) => (
          <button key={s.id} className="btn btn-sample" disabled={busy} onClick={() => useSample(s)} title={s.blurb}>
            {s.title}
          </button>
        ))}
      </div>

      <label className="field">
        <span>Or upload documents (.txt, .pdf)</span>
        <input
          type="file"
          multiple
          accept=".txt,.pdf,.png,.jpg,.jpeg"
          onChange={(e) => setFiles(Array.from(e.target.files))}
        />
      </label>
      {files.length > 0 && <div className="hint">{files.length} file(s) selected</div>}
      <button className="btn btn-primary" disabled={busy || files.length === 0} onClick={() => submit(files)}>
        {busy ? 'Submitting...' : 'Submit claim'}
      </button>
      {error && <div className="error" role="alert">{error}</div>}
    </Card>
  )
}
