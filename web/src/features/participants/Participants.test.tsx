import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ParticipantRow } from '@/client/types.gen'
import { Participants } from './Participants'

const sdk = vi.hoisted(() => ({
  listParticipants: vi.fn(),
  renameParticipant: vi.fn(),
  mergeParticipants: vi.fn(),
}))

vi.mock('@/client/sdk.gen', () => ({
  getMeetingDrilldown: vi.fn(),
  getMoment: vi.fn(),
  approveMomentArtifacts: vi.fn(),
  listMeetingMoments: vi.fn(),
  getHealth: vi.fn(),
  listMeetings: vi.fn(),
  streamJobEvents: vi.fn(),
  searchCorpus: vi.fn(),
  getJob: vi.fn(),
  createIngest: vi.fn(),
  getRecording: vi.fn(),
  getMediaFile: vi.fn(),
  listParticipants: sdk.listParticipants,
  renameParticipant: sdk.renameParticipant,
  mergeParticipants: sdk.mergeParticipants,
}))

function row(overrides: Partial<ParticipantRow> = {}): ParticipantRow {
  return {
    id: 'p-1',
    identityKey: 'mail:one@contoso.com',
    displayName: 'One Person',
    normalizedName: 'one person',
    mergedIntoParticipantId: null,
    createdAt: '2026-08-05T12:00:00Z',
    updatedAt: '2026-08-05T12:00:00Z',
    ...overrides,
  }
}

function answers(rows: Array<ParticipantRow>) {
  sdk.listParticipants.mockResolvedValue({ data: rows, error: undefined })
}

beforeEach(() => {
  sdk.listParticipants.mockReset()
  sdk.renameParticipant.mockReset()
  sdk.mergeParticipants.mockReset()
})

describe('Participants', () => {
  it('lists every row, canonical and merged-away', async () => {
    answers([
      row(),
      row({ id: 'p-2', displayName: 'Absorbed', mergedIntoParticipantId: 'p-1' }),
    ])
    render(<Participants />)

    expect(await screen.findByTestId('participant-row-p-1')).toHaveTextContent('One Person')
    expect(screen.getByTestId('merged-away-p-2')).toHaveTextContent(
      'Absorbed — merged into One Person',
    )
  })

  it('renames a participant and reflects the new name without a reload', async () => {
    answers([row()])
    sdk.renameParticipant.mockResolvedValue({
      data: row({ displayName: 'New Name' }),
      error: undefined,
    })
    render(<Participants />)

    await userEvent.click(await screen.findByTestId('rename-start-p-1'))
    const input = screen.getByTestId('rename-input-p-1') as HTMLInputElement
    await userEvent.clear(input)
    await userEvent.type(input, 'New Name')
    await userEvent.click(screen.getByTestId('rename-save-p-1'))

    expect(sdk.renameParticipant).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { participant_id: 'p-1' },
        body: { displayName: 'New Name' },
      }),
    )
    expect(await screen.findByTestId('participant-row-p-1')).toHaveTextContent('New Name')
    expect(screen.queryByTestId('rename-input-p-1')).toBeNull()
  })

  it('gives the rename input an accessible name', async () => {
    answers([row()])
    render(<Participants />)

    await userEvent.click(await screen.findByTestId('rename-start-p-1'))
    expect(screen.getByRole('textbox', { name: 'Rename One Person' })).toBe(
      screen.getByTestId('rename-input-p-1'),
    )
  })


  it('shows an error and leaves the row editable when a rename is refused', async () => {
    answers([row()])
    sdk.renameParticipant.mockResolvedValue({
      data: undefined,
      error: {
        type: 'urn:meetingminer:problem:already-merged',
        title: 'Conflict',
        status: 409,
        detail: 'participant p-1 was merged away',
      },
    })
    render(<Participants />)

    await userEvent.click(await screen.findByTestId('rename-start-p-1'))
    await userEvent.click(screen.getByTestId('rename-save-p-1'))

    expect(await screen.findByTestId('rename-error-p-1')).toHaveTextContent(
      'already merged away',
    )
    expect(screen.getByTestId('rename-input-p-1')).toBeInTheDocument()
  })

  it('merges one participant into another and replaces the list with the response', async () => {
    answers([row(), row({ id: 'p-2', displayName: 'Duplicate' })])
    sdk.mergeParticipants.mockResolvedValue({
      data: [row(), row({ id: 'p-2', displayName: 'Duplicate', mergedIntoParticipantId: 'p-1' })],
      error: undefined,
    })
    render(<Participants />)

    await screen.findByTestId('participant-row-p-2')
    await userEvent.selectOptions(screen.getByTestId('merge-select-p-2'), 'p-1')
    expect(screen.getByRole('option', { name: 'One Person (mail:one@contoso.com)' })).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('merge-button-p-2'))

    expect(sdk.mergeParticipants).toHaveBeenCalledWith(
      expect.objectContaining({
        path: { participant_id: 'p-2' },
        body: { intoParticipantId: 'p-1' },
      }),
    )
    expect(await screen.findByTestId('merged-away-p-2')).toHaveTextContent(
      'merged into One Person',
    )
  })

  it('gives each merge picker an accessible name and serializes merges globally', async () => {
    answers([
      row(),
      row({ id: 'p-2', displayName: 'Duplicate' }),
      row({ id: 'p-3', displayName: 'Other' }),
    ])
    let resolveMerge!: (value: { data: Array<ParticipantRow>; error: undefined }) => void
    sdk.mergeParticipants.mockReturnValue(
      new Promise((resolve) => {
        resolveMerge = resolve
      }),
    )
    render(<Participants />)

    await screen.findByTestId('participant-row-p-3')
    expect(screen.getByRole('combobox', { name: 'Merge Duplicate into' })).toBe(
      screen.getByTestId('merge-select-p-2'),
    )
    await userEvent.selectOptions(screen.getByTestId('merge-select-p-2'), 'p-1')
    await userEvent.click(screen.getByTestId('merge-button-p-2'))

    expect(screen.getByTestId('merge-button-p-3')).toBeDisabled()
    resolveMerge({
      data: [
        row(),
        row({ id: 'p-2', mergedIntoParticipantId: 'p-1' }),
        row({ id: 'p-3', displayName: 'Other' }),
      ],
      error: undefined,
    })
    await screen.findByTestId('merged-away-p-2')
  })

  it('shows an error and leaves the list unchanged when a merge is refused', async () => {
    answers([row(), row({ id: 'p-2', displayName: 'Duplicate' })])
    sdk.mergeParticipants.mockResolvedValue({
      data: undefined,
      error: {
        type: 'urn:meetingminer:problem:merge-target-not-canonical',
        title: 'Conflict',
        status: 409,
        detail: 'participant p-1 is itself merged away',
      },
    })
    render(<Participants />)

    await screen.findByTestId('participant-row-p-2')
    await userEvent.selectOptions(screen.getByTestId('merge-select-p-2'), 'p-1')
    await userEvent.click(screen.getByTestId('merge-button-p-2'))

    expect(await screen.findByTestId('merge-error-p-2')).toHaveTextContent(
      'merge onto its survivor instead',
    )
    expect(screen.getByTestId('participant-row-p-2')).toBeInTheDocument()
    expect(screen.queryByTestId('merged-away-p-2')).toBeNull()
  })

  it('associates a merge error with the row that failed, not a global region', async () => {
    answers([
      row(),
      row({ id: 'p-2', displayName: 'Duplicate' }),
      row({ id: 'p-3', displayName: 'Another' }),
    ])
    sdk.mergeParticipants.mockResolvedValue({
      data: undefined,
      error: {
        type: 'urn:meetingminer:problem:merge-target-not-canonical',
        title: 'Conflict',
        status: 409,
        detail: 'participant p-1 is itself merged away',
      },
    })
    render(<Participants />)

    await screen.findByTestId('participant-row-p-2')
    await userEvent.selectOptions(screen.getByTestId('merge-select-p-2'), 'p-1')
    await userEvent.click(screen.getByTestId('merge-button-p-2'))

    await screen.findByTestId('merge-error-p-2')
    // Row p-3 never attempted a merge — it must carry no error of its own.
    expect(screen.queryByTestId('merge-error-p-3')).toBeNull()
  })

  it('renders a duplicate-name hint for canonical rows sharing a normalized name', async () => {
    answers([
      row({ id: 'p-1', displayName: 'Tim Goeke', normalizedName: 'tim goeke' }),
      row({ id: 'p-2', displayName: 'Goeke, Tim', normalizedName: 'tim goeke' }),
      row({ id: 'p-3', displayName: 'Someone Else', normalizedName: 'someone else' }),
    ])
    render(<Participants />)

    const hint = await screen.findByTestId('duplicate-hint-tim goeke')
    expect(hint).toHaveTextContent('Tim Goeke')
    expect(hint).toHaveTextContent('Goeke, Tim')
    expect(screen.queryByTestId('duplicate-hint-someone else')).toBeNull()
  })

  it('names the api address when the list cannot be reached', async () => {
    sdk.listParticipants.mockRejectedValue(new Error('connection refused'))
    render(<Participants />)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('connection refused')
  })

  it('loads the list on mount', async () => {
    answers([row()])
    render(<Participants />)

    await waitFor(() => expect(sdk.listParticipants).toHaveBeenCalledTimes(1))
    expect(await screen.findByTestId('participants-list')).toBeInTheDocument()
  })
})
