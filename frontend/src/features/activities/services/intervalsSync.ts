import { apiFetch } from '@/services/http'

/** Lifecycle state reported by the host intervals.icu sync bridge. */
export type IntervalsSyncState = 'idle' | 'running' | 'unknown'

/** Whitelisted outcome codes written by the host sync runner. */
export type IntervalsSyncResult =
  'ok' | 'partial' | 'missing_key' | 'auth_rejected' | 'list_failed' | 'error'

/** How the latest intervals.icu sync run was started. */
export type IntervalsSyncTrigger = 'manual' | 'scheduled'

/** Per-run activity counters reported by the host sync runner. */
export interface IntervalsSyncCounts {
  done: number
  failed: number
  gave_up: number
  skipped: number
  pending: number
}

/** Response when intervals.icu sync is disabled or not visible to the caller. */
export interface IntervalsSyncStatusDisabled {
  enabled: false
}

/** Response when intervals.icu sync is enabled for the current owner. */
export interface IntervalsSyncStatusEnabled {
  enabled: true
  state: IntervalsSyncState
  last_started_at: string | null
  last_finished_at: string | null
  last_result: IntervalsSyncResult | null
  counts: IntervalsSyncCounts | null
  trigger: IntervalsSyncTrigger | null
  last_requested_at: string | null
  request_pending: boolean
}

/** Union payload returned by `GET /api/v1/workbench/intervals-sync`. */
export type IntervalsSyncStatus = IntervalsSyncStatusDisabled | IntervalsSyncStatusEnabled

/** Payload returned by `POST /api/v1/workbench/intervals-sync/requests`. */
export interface IntervalsSyncRequestAccepted {
  accepted: true
  requested_at: string
}

/**
 * Fetches the whitelisted intervals.icu sync bridge status for the current user.
 *
 * @param signal - Optional abort signal forwarded from TanStack Query.
 * @returns Enabled status summary or `{ enabled: false }`.
 */
export async function fetchIntervalsSyncStatus(signal?: AbortSignal): Promise<IntervalsSyncStatus> {
  return apiFetch<IntervalsSyncStatus>('/workbench/intervals-sync', { signal })
}

/**
 * Queues a manual intervals.icu sync request via the host bridge trigger file.
 *
 * @param signal - Optional abort signal.
 * @returns Confirmation with the UTC request timestamp.
 */
export async function requestIntervalsSync(
  signal?: AbortSignal,
): Promise<IntervalsSyncRequestAccepted> {
  return apiFetch<IntervalsSyncRequestAccepted>('/workbench/intervals-sync/requests', {
    method: 'POST',
    signal,
  })
}
