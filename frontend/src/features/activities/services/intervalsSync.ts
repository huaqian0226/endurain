import { apiFetch } from '@/services/http'

/** Lifecycle state reported by the host intervals.icu sync bridge. */
export type IntervalsSyncState = 'idle' | 'running' | 'unknown'

/** Whitelisted outcome codes written by the host sync runner. */
export type IntervalsSyncResult =
  'ok' | 'partial' | 'missing_key' | 'auth_rejected' | 'list_failed' | 'error'

/** How the latest intervals.icu sync run was started. */
export type IntervalsSyncTrigger = 'manual' | 'scheduled'

/** Whitelisted outcome codes for the latest intervals.icu delete execution. */
export type IntervalsSyncDeleteResult = 'ok' | 'not_found' | 'rejected' | 'failed' | 'pending'

/** Per-run activity counters reported by the host sync runner. */
export interface IntervalsSyncCounts {
  done: number
  failed: number
  gave_up: number
  skipped: number
  pending: number
}

/** Whitelisted summary of the latest intervals.icu delete execution. */
export interface IntervalsSyncLastDelete {
  requested_at: string | null
  finished_at: string | null
  result: IntervalsSyncDeleteResult
  activity_id: number
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
  last_delete: IntervalsSyncLastDelete | null
  pending_deletes: number
}

/** Union payload returned by `GET /api/v1/workbench/intervals-sync`. */
export type IntervalsSyncStatus = IntervalsSyncStatusDisabled | IntervalsSyncStatusEnabled

/** Payload returned by `POST /api/v1/workbench/intervals-sync/requests`. */
export interface IntervalsSyncRequestAccepted {
  accepted: true
  requested_at: string
}

/** Payload returned by `GET /api/v1/workbench/intervals-sync/activities/{id}`. */
export interface IntervalsSyncActivityLookup {
  intervals_id: string | null
}

/** Payload returned by `POST /api/v1/workbench/intervals-sync/delete-requests`. */
export interface IntervalsSyncDeleteRequestAccepted {
  accepted: true
  request_id: string
  intervals_id: string
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

/**
 * Checks whether an Endurain activity was imported from intervals.icu.
 *
 * @param activityId - Endurain activity identifier.
 * @param signal - Optional abort signal forwarded from TanStack Query.
 * @returns The validated intervals.icu activity id or `null`.
 */
export async function fetchIntervalsActivity(
  activityId: number,
  signal?: AbortSignal,
): Promise<IntervalsSyncActivityLookup> {
  return apiFetch<IntervalsSyncActivityLookup>(
    `/workbench/intervals-sync/activities/${activityId}`,
    {
      signal,
    },
  )
}

/**
 * Queues an intervals.icu delete request on the host bridge for an imported activity.
 *
 * @param activityId - Endurain activity identifier.
 * @param signal - Optional abort signal.
 * @returns Confirmation containing the queued request id and intervals.icu id.
 */
export async function requestIntervalsDelete(
  activityId: number,
  signal?: AbortSignal,
): Promise<IntervalsSyncDeleteRequestAccepted> {
  return apiFetch<IntervalsSyncDeleteRequestAccepted>('/workbench/intervals-sync/delete-requests', {
    method: 'POST',
    body: JSON.stringify({ activity_id: activityId }),
    signal,
  })
}
