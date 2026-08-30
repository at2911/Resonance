import type { Claim } from '../types/api'

function fmtTime(ts: string): string {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

/** Answers "why does the AI believe this?" — provenance for one claim,
 * per the spec's evidence-provenance requirement. Renders only fields
 * that actually exist on the Claim (speaker, timestamp, source text,
 * evidence) — never fabricates a justification. */
export function EvidencePanel({ claim, speakerName }: { claim: Claim; speakerName?: string }) {
  return (
    <div
      data-testid="evidence-panel"
      style={{
        marginTop: 8,
        paddingTop: 8,
        borderTop: '1px solid var(--border)',
        fontSize: 12,
      }}
    >
      <div>
        <strong>Speaker:</strong> {speakerName ?? 'Unknown'}
      </div>
      <div>
        <strong>Time:</strong> {fmtTime(claim.timestamp)}
      </div>
      <div>
        <strong>Source utterance:</strong> “{claim.text}”
      </div>
      <div>
        <strong>Evidence:</strong> {claim.evidence ?? 'Not stated'}
      </div>
      {claim.entities.length > 0 && (
        <div>
          <strong>Entities:</strong> {claim.entities.join(', ')}
        </div>
      )}
    </div>
  )
}
