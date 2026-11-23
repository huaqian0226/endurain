import { computed, type MaybeRefOrGetter, toValue } from 'vue'
import { storeToRefs } from 'pinia'
import { useMutation, useQuery } from '@tanstack/vue-query'

import { queryKeys } from '@/services/queryKeys'
import { useAuthStore } from '@/features/auth/stores/auth'
import {
  fetchIntervalsSyncStatus,
  requestIntervalsSync,
  type IntervalsSyncRequestAccepted,
  type IntervalsSyncStatus,
} from '@/features/activities/services/intervalsSync'

/** Polling cadence while waiting for a requested sync run to complete. */
export const INTERVALS_SYNC_POLL_MS = 5_000

/** Maximum polling duration after a manual sync request (3 minutes). */
export const INTERVALS_SYNC_POLL_TIMEOUT_MS = 180_000

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
