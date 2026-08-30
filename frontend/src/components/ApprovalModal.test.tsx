import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ExternalAction } from '../types/api'
import { ApprovalModal } from './ApprovalModal'

function makeEA(overrides: Partial<ExternalAction> = {}): ExternalAction {
  return {
    id: 'ea1',
    action_type: 'SLACK_MESSAGE',
    payload: { channel: '#payments-incident', text: 'Payment API errors confirmed.' },
    idempotency_key: 'k1',
    proposed_at: '2026-08-30T10:00:00Z',
    approval_status: 'PENDING',
    approved_by: null,
    approved_at: null,
    executed_at: null,
    execution_status: 'NOT_EXECUTED',
    execution_result: null,
    ...overrides,
  }
}

describe('ApprovalModal — the human approval gate', () => {
  it('shows Approve/Reject for a PENDING proposal and never shows an Execute button yet', () => {
    render(
      <ApprovalModal externalAction={makeEA()} busy={false} onApprove={vi.fn()} onReject={vi.fn()} onExecute={vi.fn()} onClose={vi.fn()} />,
    )
    expect(screen.getByTestId('btn-approve')).toBeInTheDocument()
    expect(screen.getByTestId('btn-reject')).toBeInTheDocument()
    expect(screen.queryByTestId('btn-execute')).not.toBeInTheDocument()
  })

  it('calls onApprove only when Approve & Send is clicked', () => {
    const onApprove = vi.fn()
    render(
      <ApprovalModal externalAction={makeEA()} busy={false} onApprove={onApprove} onReject={vi.fn()} onExecute={vi.fn()} onClose={vi.fn()} />,
    )
    fireEvent.click(screen.getByTestId('btn-approve'))
    expect(onApprove).toHaveBeenCalledTimes(1)
  })

  it('calls onReject only when Reject is clicked', () => {
    const onReject = vi.fn()
    render(
      <ApprovalModal externalAction={makeEA()} busy={false} onApprove={vi.fn()} onReject={onReject} onExecute={vi.fn()} onClose={vi.fn()} />,
    )
    fireEvent.click(screen.getByTestId('btn-reject'))
    expect(onReject).toHaveBeenCalledTimes(1)
  })

  it('shows a Send action once approved but not yet executed, and hides approve/reject', () => {
    render(
      <ApprovalModal
        externalAction={makeEA({ approval_status: 'APPROVED', approved_by: 'ic-alice' })}
        busy={false}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onExecute={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    expect(screen.queryByTestId('btn-approve')).not.toBeInTheDocument()
    expect(screen.queryByTestId('btn-reject')).not.toBeInTheDocument()
    expect(screen.getByTestId('btn-execute')).toHaveTextContent('Send Now')
  })

  it('offers a retry, not a fresh send, after a FAILED execution — never silently hides the failure', () => {
    render(
      <ApprovalModal
        externalAction={makeEA({ approval_status: 'APPROVED', execution_status: 'FAILED', execution_result: 'Slack API error: channel_not_found' })}
        busy={false}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onExecute={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getByTestId('btn-execute')).toHaveTextContent('Retry Send')
    expect(screen.getByText(/channel_not_found/)).toBeInTheDocument()
  })

  it('shows no action buttons once the message has actually been sent', () => {
    render(
      <ApprovalModal
        externalAction={makeEA({ approval_status: 'APPROVED', execution_status: 'SUCCEEDED', execution_result: 'Posted to Slack (ts=1.1)' })}
        busy={false}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onExecute={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    expect(screen.queryByTestId('btn-approve')).not.toBeInTheDocument()
    expect(screen.queryByTestId('btn-execute')).not.toBeInTheDocument()
    expect(screen.getByText(/ts=1.1/)).toBeInTheDocument()
  })
})
