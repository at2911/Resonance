import { useState } from 'react'
import type { Claim } from '../types/api'
import { EvidencePanel } from './EvidencePanel'

const TYPE_ICON: Record<string, string> = {
  FACT: '✓',
  HYPOTHESIS: '?',
  DECISION: '⚑',
  ACTION: '→',
  QUESTION: '?',
  RISK: '⚠',
  UPDATE: '↻',
}

export function ClaimCard({ claim, speakerName }: { claim: Claim; speakerName?: string }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="card" data-testid="claim-card" data-claim-type={claim.type}>
      <div className="card-top">
        <span className={`tag tag-${claim.type}`}>
          {TYPE_ICON[claim.type] ?? ''} {claim.type}
        </span>
        <span className={`status-chip ${claim.status}`}>{claim.status}</span>
      </div>
      <div style={{ lineHeight: 1.4 }}>{claim.normalized_claim}</div>
      <div className="evidence">
        confidence {(claim.confidence * 100).toFixed(0)}%
        {speakerName ? ` · ${speakerName}` : ''}
        {' · '}
        <button
          className="btn small secondary"
          style={{ padding: '1px 8px', fontSize: 10.5 }}
          onClick={() => setExpanded((v) => !v)}
          data-testid="claim-evidence-toggle"
        >
          {expanded ? 'Hide evidence' : 'Why?'}
        </button>
      </div>
      {expanded && <EvidencePanel claim={claim} speakerName={speakerName} />}
    </div>
  )
}
