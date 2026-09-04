import type { TimelineEvent } from '../types/api'

function fmtTime(ts: string): string {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

/** Answers "what's new since I last looked?" — every field here comes
 * straight from the incident's own timeline/external_actions, computed by
 * Dashboard (see `sinceIso`/`sinceLabel`); this component never decides
 * what counts as "changed" on its own. */
export function WhatChanged({
  events,
  sinceIso,
  sinceLabel,
}: {
  events: TimelineEvent[]
  sinceIso: string
  sinceLabel: string
}) {
  const changed = events.filter((e) => e.timestamp > sinceIso).sort((a, b) => b.timestamp.localeCompare(a.timestamp))

  return (
    <div className="panel" data-testid="what-changed">
      <h2>
        What Changed{' '}
        {changed.length > 0 && (
          <span className="status-chip" style={{ marginLeft: 6, textTransform: 'none' }} data-testid="what-changed-count">
            {changed.length} new
          </span>
        )}
      </h2>
      <div className="body" style={{ maxHeight: 220 }}>
        <div style={{ color: 'var(--dim)', fontSize: 10.5, marginBottom: 6 }}>{sinceLabel}</div>
        {changed.length === 0 ? (
          <div className="empty">Nothing new.</div>
        ) : (
          changed.map((e) => (
            <div
              key={e.id}
              data-testid="what-changed-item"
              style={{ display: 'flex', gap: 10, padding: '6px 0', borderBottom: '1px dashed var(--border)', fontSize: 12.5 }}
            >
              <span style={{ color: 'var(--dim)', whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>
                {fmtTime(e.timestamp)}
              </span>
              <span>
                <span style={{ fontWeight: 700 }}>{e.event_type.replace(/_/g, ' ')}</span> — {e.content}
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
