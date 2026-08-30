import type { TimelineEvent } from '../types/api'

function fmtTime(ts: string): string {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function Timeline({ events }: { events: TimelineEvent[] }) {
  const ordered = [...events].reverse()
  return (
    <div className="panel">
      <h2>Live Incident Timeline</h2>
      <div className="body" style={{ maxHeight: 460 }}>
        {ordered.length === 0 ? (
          <div className="empty">No events yet.</div>
        ) : (
          ordered.map((e) => (
            <div
              key={e.id}
              data-testid="timeline-item"
              style={{
                display: 'flex',
                gap: 10,
                padding: '7px 0',
                borderBottom: '1px dashed var(--border)',
                fontSize: 12.5,
              }}
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
