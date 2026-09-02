import type { Risk } from '../types/api'

export function RiskCard({ risk }: { risk: Risk }) {
  return (
    <div className="card" data-testid="risk-card">
      <div className="card-top">
        <span className="tag tag-RISK">⚠ {risk.severity}</span>
        <span className="status-chip">{risk.status}</span>
      </div>
      <div>{risk.description}</div>
      <div className="evidence">confidence {(risk.confidence * 100).toFixed(0)}%</div>
      {risk.mitigation && <div className="evidence">Mitigation: {risk.mitigation}</div>}
    </div>
  )
}
