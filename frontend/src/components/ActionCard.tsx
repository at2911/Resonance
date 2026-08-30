import type { Action } from '../types/api'

export function ActionCard({ action }: { action: Action }) {
  return (
    <div className="card" data-testid="action-card">
      <div className="card-top">
        <span className="tag tag-ACTION">
          {action.owner ?? 'UNASSIGNED'} → {action.priority}
        </span>
        <span className="status-chip">{action.status}</span>
      </div>
      <div>{action.description}</div>
      {action.completion_evidence && <div className="evidence">Completed: {action.completion_evidence}</div>}
    </div>
  )
}
