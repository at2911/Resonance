import { useState } from 'react'
import type { Participant, ParticipantRole } from '../types/api'

const ROLES: ParticipantRole[] = [
  'INCIDENT_COMMANDER',
  'BACKEND_ENGINEER',
  'SRE',
  'SUPPORT',
  'BUSINESS_STAKEHOLDER',
  'UNKNOWN',
]

function fmtJoined(ts: string): string {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/** Read-only display of a Participant, plus an optional inline role
 * correction control. The extraction pipeline is the only thing that
 * ever changes role/role_confidence automatically (via
 * IncidentStateService.update_role_if_more_confident); onCorrectRole, if
 * provided, calls the separate always-applies
 * correct_participant_role endpoint — a human correction is
 * authoritative regardless of the AI's current confidence. This never
 * invents a role or confidence value; UNKNOWN at 0% is rendered exactly
 * as such rather than hidden or guessed at. */
export function ParticipantCard({
  participant,
  onCorrectRole,
  busy,
}: {
  participant: Participant
  onCorrectRole?: (participantId: string, role: ParticipantRole) => void
  busy?: boolean
}) {
  const [pendingRole, setPendingRole] = useState<ParticipantRole>(participant.role)
  const isUnknownRole = participant.role === 'UNKNOWN'
  const hasPendingChange = pendingRole !== participant.role

  return (
    <div className="card" data-testid="participant-card">
      <div className="card-top">
        <span className={`tag ${isUnknownRole ? 'tag-QUESTION' : 'tag-ACTION'}`} data-testid="participant-role-tag">
          {participant.role.replace(/_/g, ' ')}
        </span>
        <span className="status-chip" data-testid="participant-role-confidence">
          {(participant.role_confidence * 100).toFixed(0)}% sure
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <strong>{participant.name}</strong>
        {participant.agora_uid && (
          <span
            className="status-chip"
            title={`Joined via a real Agora voice session (uid ${participant.agora_uid})`}
            data-testid="participant-voice-badge"
          >
            🎙 voice
          </span>
        )}
      </div>
      <div className="evidence">joined at {fmtJoined(participant.joined_at)}</div>
      {onCorrectRole && (
        <div style={{ display: 'flex', gap: 6, marginTop: 6, alignItems: 'center' }}>
          <select
            value={pendingRole}
            onChange={(e) => setPendingRole(e.target.value as ParticipantRole)}
            data-testid="participant-role-select"
            style={{
              background: 'var(--panel2)',
              border: '1px solid var(--border)',
              color: 'var(--text)',
              borderRadius: 6,
              padding: '3px 6px',
              fontSize: 11,
            }}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r.replace(/_/g, ' ')}
              </option>
            ))}
          </select>
          <button
            className="btn small secondary"
            style={{ padding: '2px 8px', fontSize: 10.5 }}
            disabled={!hasPendingChange || busy}
            onClick={() => onCorrectRole(participant.id, pendingRole)}
            data-testid="participant-correct-role"
          >
            Correct
          </button>
        </div>
      )}
    </div>
  )
}
