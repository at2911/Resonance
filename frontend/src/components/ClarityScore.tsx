import type { ClarityScoreBreakdown } from '../types/api'

/** The score itself is computed entirely server-side
 * (IncidentStateService.compute_clarity_score) — this component only
 * renders the breakdown, it never derives or recomputes the number. */
export function ClarityScore({ clarity }: { clarity: ClarityScoreBreakdown | null }) {
  return (
    <div className="panel">
      <h2>Clarity</h2>
      <div className="body">
        {clarity ? (
          <>
            <div style={{ fontSize: 36, fontWeight: 700 }} data-testid="clarity-score">
              {clarity.score}%
            </div>
            <div style={{ color: 'var(--dim)', fontSize: 11.5, lineHeight: 1.7, marginTop: 6 }}>
              <div>{clarity.confirmed_facts} confirmed facts</div>
              <div>{clarity.unresolved_hypotheses} unresolved hypotheses</div>
              <div>{clarity.open_conflicts} open conflicts</div>
              <div>{clarity.critical_information_gaps} critical gaps</div>
              <div>{clarity.unowned_open_actions} unowned actions</div>
            </div>
            <div
              style={{
                marginTop: 10,
                paddingTop: 8,
                borderTop: '1px solid var(--border)',
                fontSize: 12,
                fontWeight: 600,
                color: clarity.root_cause_confirmed ? 'var(--fact)' : 'var(--critical)',
              }}
              data-testid="root-cause-indicator"
            >
              {clarity.root_cause_confirmed ? '✓ Root cause confirmed' : '⚠ Root cause unresolved'}
            </div>
          </>
        ) : (
          <div className="empty">—</div>
        )}
      </div>
    </div>
  )
}
