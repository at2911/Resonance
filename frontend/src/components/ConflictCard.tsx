import type { Claim, Conflict } from '../types/api'

export function ConflictCard({
  conflict,
  claimA,
  claimB,
}: {
  conflict: Conflict
  claimA?: Claim
  claimB?: Claim
}) {
  return (
    <div className="card conflict-card" data-testid="conflict-card">
      <div className="card-top">
        <span className="tag" style={{ background: '#3a1c1c', color: '#ff8080' }}>
          ⚠ CONFLICT — {conflict.conflict_type.replace(/_/g, ' ')}
        </span>
        <span className="status-chip">{conflict.status}</span>
      </div>
      <div>{conflict.explanation}</div>
      {(claimA || claimB) && (
        <div className="evidence" style={{ marginTop: 6 }}>
          {claimA && <div>• {claimA.normalized_claim}</div>}
          {claimB && <div>• {claimB.normalized_claim}</div>}
        </div>
      )}
    </div>
  )
}
