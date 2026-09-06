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
    <div className="start-screen">
      <div className="start-screen-inner">
        <div className="start-hero">
          <div className="mark">🛰</div>
          <h1>Resonance — AI Incident Commander</h1>
          <p>
            It listens to an incident — by voice or text — and keeps a live, evidence-backed
            record of what's actually known versus what's still a guess. Pick how to start below.
          </p>
        </div>

        <div className="start-cards">
          <div className="start-card">
            <div className="kicker">Option A</div>
            <h2>Start a real incident</h2>
            <p className="desc">
              A blank incident you narrate yourself — type what's happening below, or speak to a
              live AI voice agent once it's open.
            </p>
            <div className="fields">
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Incident title"
              />
              <select value={severity} onChange={(e) => setSeverity(e.target.value as IncidentSeverity)}>
                {SEVERITIES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </div>
            <div className="start-card-spacer"></div>
            <button className="btn" disabled={busy || !title.trim()} onClick={handleCreate} data-testid="btn-create-incident">
              {busy ? 'Creating…' : 'Create Incident'}
            </button>
          </div>

          <div className="start-card">
            <div className="kicker">Option B</div>
            <h2>Run the guided demo</h2>
            <p className="desc">
              A scripted, 9-step walkthrough of a realistic incident — powered by the real
              backend, not fake data. Nothing to type, pausable anytime. Good for a first look.
            </p>
            <div className="start-card-spacer"></div>
            <button className="btn secondary" disabled={busy} onClick={handleRunDemo} data-testid="btn-run-demo">
              ▶ Run Backend Demo
            </button>
          </div>
        </div>

        {error && <div className="start-error">{error}</div>}
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
