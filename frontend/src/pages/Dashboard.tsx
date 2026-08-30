import { useMemo, useState } from 'react'
import { ActionCard } from '../components/ActionCard'
import { ApprovalModal } from '../components/ApprovalModal'
import { ClaimCard } from '../components/ClaimCard'
import { ClarityScore } from '../components/ClarityScore'
import { ConflictCard } from '../components/ConflictCard'
import { IncidentHeader } from '../components/IncidentHeader'
import { InformationGaps } from '../components/InformationGaps'
import { Timeline } from '../components/Timeline'
import { useIncident } from '../hooks/useIncident'
import { ApiError, decideExternalAction, executeExternalAction, postUtterance, proposeSlackUpdate } from '../services/api'
import type { ExternalAction } from '../types/api'

export function Dashboard({ incidentId }: { incidentId: string }) {
  const { incident, clarity, error, refresh } = useIncident(incidentId)
  const [openApprovalId, setOpenApprovalId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [banner, setBanner] = useState<string | null>(null)
  const [speakerName, setSpeakerName] = useState('Alice')
  const [utteranceText, setUtteranceText] = useState('')

  const claims = useMemo(
    () => (incident ? Object.values(incident.claims).sort((a, b) => a.timestamp.localeCompare(b.timestamp)) : []),
    [incident],
  )
  const conflicts = useMemo(() => (incident ? Object.values(incident.conflicts) : []), [incident])
  const actions = useMemo(() => (incident ? Object.values(incident.actions) : []), [incident])
  const pendingExternalActions = useMemo(
    () =>
      incident
        ? Object.values(incident.external_actions).filter(
            (ea) => ea.approval_status === 'PENDING' || (ea.approval_status === 'APPROVED' && ea.execution_status !== 'SUCCEEDED'),
          )
        : [],
    [incident],
  )
  const openApproval: ExternalAction | undefined = incident?.external_actions[openApprovalId ?? '']

  function speakerName_(id: string | null): string | undefined {
    if (!id || !incident) return undefined
    return incident.participants[id]?.name
  }

  async function handleSendUtterance() {
    if (!utteranceText.trim()) return
    setBusy(true)
    setBanner(null)
    try {
      await postUtterance(incidentId, speakerName, utteranceText)
      setUtteranceText('')
      await refresh()
    } catch (e) {
      setBanner(e instanceof ApiError ? `Extraction unavailable: ${e.message}` : 'Failed to send utterance')
    } finally {
      setBusy(false)
    }
  }

  async function handleProposeSlack() {
    setBusy(true)
    setBanner(null)
    try {
      const ea = await proposeSlackUpdate(incidentId)
      await refresh()
      setOpenApprovalId(ea.id)
    } catch (e) {
      setBanner(e instanceof ApiError ? `Slack unavailable: ${e.message}` : 'Failed to propose Slack update')
    } finally {
      setBusy(false)
    }
  }

  async function handleApprove(id: string) {
    setBusy(true)
    try {
      await decideExternalAction(incidentId, id, { approved: true, approved_by: 'ic-dashboard' })
      const executed = await executeExternalAction(incidentId, id)
      await refresh()
      if (executed) setOpenApprovalId(id)
    } catch (e) {
      setBanner(e instanceof ApiError ? e.message : 'Approval failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleReject(id: string) {
    setBusy(true)
    try {
      await decideExternalAction(incidentId, id, { approved: false, approved_by: 'ic-dashboard' })
      await refresh()
    } catch (e) {
      setBanner(e instanceof ApiError ? e.message : 'Rejection failed')
    } finally {
      setBusy(false)
    }
  }

  async function handleExecute(id: string) {
    setBusy(true)
    try {
      await executeExternalAction(incidentId, id)
      await refresh()
    } catch (e) {
      setBanner(e instanceof ApiError ? e.message : 'Execution failed')
    } finally {
      setBusy(false)
    }
  }

  if (!incident) {
    return <div style={{ padding: 20, color: 'var(--dim)' }}>{error ? `Error: ${error}` : 'Loading incident…'}</div>
  }

  return (
    <div>
      <IncidentHeader incident={incident} />

      {banner && (
        <div style={{ background: '#3a1c1c', color: '#ff8080', padding: '8px 20px', fontSize: 12.5 }}>{banner}</div>
      )}

      <main
        style={{
          display: 'grid',
          gridTemplateColumns: '260px 1.1fr 1fr',
          gap: 16,
          padding: '16px 20px',
          maxWidth: 1600,
          margin: '0 auto',
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <ClarityScore clarity={clarity} />
          <InformationGaps gaps={Object.values(incident.information_gaps)} />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Timeline events={incident.timeline} />

          <div className="panel">
            <h2>Log Utterance</h2>
            <div className="body">
              <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                <input
                  value={speakerName}
                  onChange={(e) => setSpeakerName(e.target.value)}
                  placeholder="Speaker"
                  style={{ width: 90, background: 'var(--panel2)', border: '1px solid var(--border)', color: 'var(--text)', borderRadius: 6, padding: '6px 8px' }}
                />
                <input
                  value={utteranceText}
                  onChange={(e) => setUtteranceText(e.target.value)}
                  placeholder="What did they say?"
                  onKeyDown={(e) => e.key === 'Enter' && handleSendUtterance()}
                  style={{ flex: 1, background: 'var(--panel2)', border: '1px solid var(--border)', color: 'var(--text)', borderRadius: 6, padding: '6px 8px' }}
                />
                <button className="btn" disabled={busy} onClick={handleSendUtterance} data-testid="btn-send-utterance">
                  Send
                </button>
              </div>
              <div style={{ color: 'var(--dim)', fontSize: 11 }}>
                Runs through the real extraction pipeline — requires LLM_API_KEY configured on the backend.
              </div>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="panel">
            <h2>Facts / Hypotheses / Decisions</h2>
            <div className="body">
              {claims.filter((c) => c.type !== 'ACTION' && c.type !== 'RISK').length === 0 ? (
                <div className="empty">Nothing established yet.</div>
              ) : (
                claims
                  .filter((c) => c.type !== 'ACTION' && c.type !== 'RISK')
                  .map((c) => <ClaimCard key={c.id} claim={c} speakerName={speakerName_(c.speaker_id)} />)
              )}
            </div>
          </div>

          <div className="panel">
            <h2>Conflicts</h2>
            <div className="body">
              {conflicts.length === 0 ? (
                <div className="empty">None detected.</div>
              ) : (
                conflicts.map((c) => (
                  <ConflictCard key={c.id} conflict={c} claimA={incident.claims[c.claim_a]} claimB={incident.claims[c.claim_b]} />
                ))
              )}
            </div>
          </div>

          <div className="panel">
            <h2>Actions</h2>
            <div className="body">
              {actions.length === 0 ? (
                <div className="empty">No actions assigned.</div>
              ) : (
                actions.map((a) => <ActionCard key={a.id} action={a} />)
              )}
            </div>
          </div>
        </div>
      </main>

      <footer
        style={{
          position: 'sticky',
          bottom: 0,
          background: 'var(--panel)',
          borderTop: '1px solid var(--border)',
          padding: '10px 20px',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
        }}
      >
        <strong style={{ fontSize: 12, textTransform: 'uppercase', color: 'var(--dim)' }}>AI Proposed Slack Update</strong>
        {pendingExternalActions.length === 0 ? (
          <>
            <span style={{ color: 'var(--dim)', fontSize: 12 }}>No proposal yet.</span>
            <button className="btn secondary small" style={{ marginLeft: 'auto' }} disabled={busy} onClick={handleProposeSlack}>
              Propose Slack Update
            </button>
          </>
        ) : (
          <button className="btn small" style={{ marginLeft: 'auto' }} onClick={() => setOpenApprovalId(pendingExternalActions[0].id)}>
            Review
          </button>
        )}
      </footer>

      {openApproval && (
        <ApprovalModal
          externalAction={openApproval}
          busy={busy}
          onApprove={() => handleApprove(openApproval.id)}
          onReject={() => handleReject(openApproval.id)}
          onExecute={() => handleExecute(openApproval.id)}
          onClose={() => setOpenApprovalId(null)}
        />
      )}
    </div>
  )
}
