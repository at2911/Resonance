import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, getClarity, getIncident, getSummary } from '../services/api'
import type { ClarityScoreBreakdown, FinalSummary, Incident } from '../types/api'

interface UseIncidentResult {
  incident: Incident | null
  clarity: ClarityScoreBreakdown | null
  summary: FinalSummary | null
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
}

/** Polls the three read endpoints for one incident on an interval. The
 * backend is the source of truth (per project architecture) — this hook
 * never derives or caches state beyond "the last successful response". */
export function useIncident(incidentId: string, intervalMs = 1200): UseIncidentResult {
  const [incident, setIncident] = useState<Incident | null>(null)
  const [clarity, setClarity] = useState<ClarityScoreBreakdown | null>(null)
  const [summary, setSummary] = useState<FinalSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inFlight = useRef(false)

  const refresh = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    setLoading(true)
    try {
      const [inc, clr, summ] = await Promise.all([
        getIncident(incidentId),
        getClarity(incidentId),
        getSummary(incidentId),
      ])
      setIncident(inc)
      setClarity(clr)
      setSummary(summ)
      setError(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Failed to reach backend')
    } finally {
      setLoading(false)
      inFlight.current = false
    }
  }, [incidentId])

  useEffect(() => {
    // oxlint's set-state-in-effect rule flags this, but fetching on mount
    // and on an interval IS synchronizing with an external system (the
    // backend) — the case React's own docs call out as a valid useEffect.
    // eslint-disable-next-line react/set-state-in-effect -- see comment above
    void refresh()
    const timer = setInterval(() => void refresh(), intervalMs)
    return () => clearInterval(timer)
  }, [intervalMs, refresh])

  return { incident, clarity, summary, loading, error, refresh }
}
