import type { ExternalAction } from '../types/api'

interface Props {
  externalAction: ExternalAction
  busy: boolean
  onApprove: () => void
  onReject: () => void
  onExecute: () => void
  onClose: () => void
}

/** The human-approval gate: nothing is ever posted until a person clicks
 * "Approve & Send" here, and the backend independently re-checks approval
 * before executing (mark_external_action_executing) — this component only
 * reflects that server-enforced state, it doesn't grant permission itself. */
export function ApprovalModal({ externalAction: ea, busy, onApprove, onReject, onExecute, onClose }: Props) {
  return (
    <div className="modal-overlay" data-testid="approval-modal" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <h2 style={{ margin: 0, fontSize: 13, textTransform: 'uppercase', color: 'var(--dim)' }}>
          AI Proposed Slack Update
        </h2>
        <div style={{ marginTop: 10 }}>
          <strong>Destination:</strong> {ea.payload.channel}
        </div>
        <div className="msg">{ea.payload.text}</div>
        <div style={{ marginBottom: 10, fontSize: 12 }}>
          Status: <span className="status-chip">{ea.approval_status}</span>{' '}
          {ea.execution_status !== 'NOT_EXECUTED' && <span className="status-chip">{ea.execution_status}</span>}
        </div>

        {ea.approval_status === 'PENDING' && (
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn reject" disabled={busy} onClick={onReject} data-testid="btn-reject">
              Reject
            </button>
            <button className="btn" disabled={busy} onClick={onApprove} data-testid="btn-approve">
              Approve &amp; Send
            </button>
          </div>
        )}

        {ea.approval_status === 'APPROVED' && ea.execution_status !== 'SUCCEEDED' && (
          <button className="btn" disabled={busy} onClick={onExecute} data-testid="btn-execute">
            {ea.execution_status === 'FAILED' ? 'Retry Send' : 'Send Now'}
          </button>
        )}

        {ea.execution_result && (
          <div className="evidence" style={{ marginTop: 8 }}>
            {ea.execution_result}
          </div>
        )}

        <div style={{ marginTop: 14, textAlign: 'right' }}>
          <button className="btn small secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}
