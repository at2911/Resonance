import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Participant } from '../types/api'
import { ParticipantCard } from './ParticipantCard'

function makeParticipant(overrides: Partial<Participant> = {}): Participant {
  return {
    id: 'p1',
    name: 'Alice',
    role: 'INCIDENT_COMMANDER',
    role_confidence: 0.9,
    joined_at: '2026-08-30T10:00:00Z',
    agora_uid: null,
    ...overrides,
  }
}

describe('ParticipantCard', () => {
  it('renders the name and role', () => {
    render(<ParticipantCard participant={makeParticipant()} />)
    expect(screen.getByText('Alice')).toBeInTheDocument()
    expect(screen.getByTestId('participant-role-tag')).toHaveTextContent('INCIDENT COMMANDER')
  })

  it('shows role confidence as a percentage', () => {
    render(<ParticipantCard participant={makeParticipant({ role_confidence: 0.9 })} />)
    expect(screen.getByText(/90% sure/)).toBeInTheDocument()
  })

  it('renders UNKNOWN role and 0% confidence honestly rather than hiding it', () => {
    render(<ParticipantCard participant={makeParticipant({ role: 'UNKNOWN', role_confidence: 0 })} />)
    expect(screen.getByTestId('participant-role-tag')).toHaveTextContent('UNKNOWN')
    expect(screen.getByText(/0% sure/)).toBeInTheDocument()
  })

  it('shows a voice badge only when the participant joined via Agora', () => {
    const { rerender } = render(<ParticipantCard participant={makeParticipant({ agora_uid: '12345' })} />)
    expect(screen.getByTestId('participant-voice-badge')).toBeInTheDocument()

    rerender(<ParticipantCard participant={makeParticipant({ agora_uid: null })} />)
    expect(screen.queryByTestId('participant-voice-badge')).not.toBeInTheDocument()
  })

  it('does not render a role-correction control when onCorrectRole is not passed', () => {
    render(<ParticipantCard participant={makeParticipant()} />)
    expect(screen.queryByTestId('participant-role-select')).not.toBeInTheDocument()
  })

  it('the Correct button starts disabled and only enables once a different role is picked', () => {
    render(<ParticipantCard participant={makeParticipant({ role: 'BACKEND_ENGINEER' })} onCorrectRole={vi.fn()} />)
    expect(screen.getByTestId('participant-correct-role')).toBeDisabled()

    fireEvent.change(screen.getByTestId('participant-role-select'), { target: { value: 'INCIDENT_COMMANDER' } })
    expect(screen.getByTestId('participant-correct-role')).not.toBeDisabled()
  })

  it('clicking Correct calls onCorrectRole with the participant id and the newly picked role', () => {
    const onCorrectRole = vi.fn()
    render(<ParticipantCard participant={makeParticipant({ id: 'p9', role: 'UNKNOWN' })} onCorrectRole={onCorrectRole} />)

    fireEvent.change(screen.getByTestId('participant-role-select'), { target: { value: 'SRE' } })
    fireEvent.click(screen.getByTestId('participant-correct-role'))

    expect(onCorrectRole).toHaveBeenCalledWith('p9', 'SRE')
  })
})
