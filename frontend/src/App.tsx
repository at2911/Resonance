import { useState } from 'react'
import { DemoControls } from './components/DemoControls'
import { Dashboard } from './pages/Dashboard'
import { ApiError, createIncident, startDemo } from './services/api'
import type { IncidentSeverity } from './types/api'

const SEVERITIES: IncidentSeverity[] = ['SEV1', 'SEV2', 'SEV3', 'SEV4', 'UNKNOWN']

function CreateIncidentScreen({
  onCreated,
  onDemoStarted,
}: {
  onCreated: (id: string) => void
  onDemoStarted: (id: string) => void
}) {
  const [title, setTitle] = useState('Payment API Outage')
  const [severity, setSeverity] = useState<IncidentSeverity>('SEV1')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleCreate() {
    setBusy(true)
    setError(null)
    try {
      const incident = await createIncident({ title, severity })
      onCreated(incident.id)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not reach the backend')
    } finally {
      setBusy(false)
    }
  }

  async function handleRunDemo() {
    setBusy(true)
    setError(null)
    try {
      const status = await startDemo()
      if (status.incident_id) onDemoStarted(status.incident_id)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not reach the backend')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ maxWidth: 420, margin: '80px auto', padding: 20 }}>
      <h1 style={{ fontSize: 18 }}>🛰 Resonance — Incident Commander</h1>
      <p style={{ color: 'var(--dim)', fontSize: 13 }}>Start a new incident to open the live dashboard.</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 16 }}>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Incident title"
          style={{ background: 'var(--panel2)', border: '1px solid var(--border)', color: 'var(--text)', borderRadius: 6, padding: '8px 10px' }}
        />
        <select
          value={severity}
          onChange={(e) => setSeverity(e.target.value as IncidentSeverity)}
          style={{ background: 'var(--panel2)', border: '1px solid var(--border)', color: 'var(--text)', borderRadius: 6, padding: '8px 10px' }}
        >
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <button className="btn" disabled={busy || !title.trim()} onClick={handleCreate} data-testid="btn-create-incident">
          {busy ? 'Creating…' : 'Create Incident'}
        </button>
        <button className="btn secondary" disabled={busy} onClick={handleRunDemo} data-testid="btn-run-demo">
          ▶ Run Backend Demo
        </button>
        {error && <div style={{ color: 'var(--critical)', fontSize: 12.5 }}>{error}</div>}
      </div>
    </div>
  )
}

export default function App() {
  const [incidentId, setIncidentId] = useState<string | null>(null)
  const [demoActive, setDemoActive] = useState(false)

  function handleDemoStarted(id: string) {
    setIncidentId(id)
    setDemoActive(true)
  }

  function handleDemoReset() {
    setIncidentId(null)
    setDemoActive(false)
  }

  if (!incidentId) {
    return <CreateIncidentScreen onCreated={setIncidentId} onDemoStarted={handleDemoStarted} />
  }

  return (
    <>
      {demoActive && <DemoControls onReset={handleDemoReset} />}
      <Dashboard incidentId={incidentId} />
    </>
  )
}
