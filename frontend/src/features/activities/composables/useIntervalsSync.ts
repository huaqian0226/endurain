import { computed, type MaybeRefOrGetter, toValue } from 'vue'
import { storeToRefs } from 'pinia'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'

import { queryKeys } from '@/services/queryKeys'
import { useAuthStore } from '@/features/auth/stores/auth'
import {
  fetchIntervalsActivity,
  fetchIntervalsSyncStatus,
  requestIntervalsDelete,
  requestIntervalsSync,
  type IntervalsSyncActivityLookup,
  type IntervalsSyncDeleteRequestAccepted,
  type IntervalsSyncRequestAccepted,
  type IntervalsSyncStatus,
} from '@/features/activities/services/intervalsSync'

/** Polling cadence while waiting for a requested sync run to complete. */
export const INTERVALS_SYNC_POLL_MS = 5_000

/** Maximum polling duration after a manual sync request (3 minutes). */
export const INTERVALS_SYNC_POLL_TIMEOUT_MS = 180_000

function resolveActivityId(id: MaybeRefOrGetter<number | null>): number {
  const value = toValue(id)
  return value !== null && Number.isFinite(value) && value > 0 ? value : 0
}

/**
 * Queries the intervals.icu host sync bridge status for the authenticated user.
 *
 * Polls every 5 seconds while `polling` is `true`.
 *
 * @param polling - Reactive flag enabling periodic polling.
 * @returns TanStack Query result for the sync bridge status.
 */
export function useIntervalsSyncQuery(polling: MaybeRefOrGetter<boolean> = false) {
  const { isAuthenticated } = storeToRefs(useAuthStore())

  return useQuery<IntervalsSyncStatus, Error>({
    queryKey: queryKeys.activities.intervalsSync(),
    queryFn: ({ signal }) => fetchIntervalsSyncStatus(signal),
    enabled: isAuthenticated,
    refetchInterval: computed(() => (toValue(polling) ? INTERVALS_SYNC_POLL_MS : false)),
  })
}

/**
 * Triggers a manual intervals.icu sync request via `POST /workbench/intervals-sync/requests`.
 *
 * @returns TanStack Query mutation for queuing a sync request.
 */
export function useRequestIntervalsSyncMutation() {
  return useMutation<IntervalsSyncRequestAccepted, Error, void>({
    mutationKey: [...queryKeys.activities.intervalsSync(), 'request'],
    mutationFn: () => requestIntervalsSync(),
  })
}

/**
 * Checks whether an activity was imported from intervals.icu when the delete
 * confirmation dialog is open.
 *
 * @param activityId - Reactive Endurain activity id.
 * @param enabled - Reactive gate (typically dialog open state).
 * @returns TanStack Query result containing `{ intervals_id }`.
 */
export function useIntervalsActivityQuery(
  activityId: MaybeRefOrGetter<number | null>,
  enabled: MaybeRefOrGetter<boolean>,
) {
  const { isAuthenticated } = storeToRefs(useAuthStore())

  return useQuery<IntervalsSyncActivityLookup, Error>({
    queryKey: computed(() => queryKeys.activities.intervalsActivity(resolveActivityId(activityId))),
    queryFn: ({ signal }) => fetchIntervalsActivity(resolveActivityId(activityId), signal),
    enabled: computed(
      () => isAuthenticated.value && toValue(enabled) && resolveActivityId(activityId) > 0,
    ),
    retry: false,
    staleTime: 0,
  })
}

/**
 * Queues a remote intervals.icu deletion for an imported activity.
 *
 * @returns TanStack Query mutation for posting a delete request.
 */
export function useRequestIntervalsDeleteMutation() {
  const client = useQueryClient()

  return useMutation<IntervalsSyncDeleteRequestAccepted, Error, number>({
    mutationKey: [...queryKeys.activities.intervalsSync(), 'delete-request'],
    mutationFn: (activityId) => requestIntervalsDelete(activityId),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: queryKeys.activities.intervalsSync() })
    },
  })
}
