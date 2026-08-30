import type { InformationGap } from '../types/api'

export function InformationGaps({ gaps }: { gaps: InformationGap[] }) {
  const open = gaps.filter((g) => g.status === 'OPEN')
  return (
    <div className="panel">
      <h2>Information Gaps</h2>
      <div className="body">
        {open.length === 0 ? (
          <div className="empty">None flagged.</div>
        ) : (
          open.map((g) => (
            <div
              key={g.id}
              className={`card ${g.importance === 'CRITICAL' ? 'gap-critical' : 'gap-normal'}`}
              data-testid="gap-card"
            >
              <span
                className="tag"
                style={{
                  background: g.importance === 'CRITICAL' ? '#3a1c1c' : '#222',
                  color: g.importance === 'CRITICAL' ? '#ff8080' : '#aaa',
                }}
              >
                {g.importance}
              </span>{' '}
              {g.description}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
