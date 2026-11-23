<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQueryClient } from '@tanstack/vue-query'
import { RefreshCw } from '@lucide/vue'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { HttpError } from '@/services/http'
import { queryKeys } from '@/services/queryKeys'
import {
  INTERVALS_SYNC_POLL_TIMEOUT_MS,
  useIntervalsSyncQuery,
  useRequestIntervalsSyncMutation,
} from '@/features/activities/composables/useIntervalsSync'
import type {
  IntervalsSyncDeleteResult,
  IntervalsSyncResult,
  IntervalsSyncStatusEnabled,
} from '@/features/activities/services/intervalsSync'

type FeedbackKind = 'requested' | 'conflictRunning' | 'conflictRecent' | 'requestFailed' | null

const RESULT_LABEL_KEYS: Record<IntervalsSyncResult, string> = {
  ok: 'activities.intervalsSync.results.ok',
  partial: 'activities.intervalsSync.results.partial',
  missing_key: 'activities.intervalsSync.results.missingKey',
  auth_rejected: 'activities.intervalsSync.results.authRejected',
  list_failed: 'activities.intervalsSync.results.listFailed',
  error: 'activities.intervalsSync.results.error',
}

const DELETE_RESULT_LABEL_KEYS: Record<IntervalsSyncDeleteResult, string> = {
  ok: 'activities.intervalsSync.deleteResults.ok',
  not_found: 'activities.intervalsSync.deleteResults.notFound',
  rejected: 'activities.intervalsSync.deleteResults.rejected',
  failed: 'activities.intervalsSync.deleteResults.failed',
  pending: 'activities.intervalsSync.deleteResults.pending',
}

const { t, locale } = useI18n()
const queryClient = useQueryClient()

const isPolling = ref(false)
const feedback = ref<FeedbackKind>(null)
let pollBaselineUpdatedAt = 0
let pollTimeoutHandle: ReturnType<typeof setTimeout> | undefined

const statusQuery = useIntervalsSyncQuery(isPolling)
const requestMutation = useRequestIntervalsSyncMutation()

const enabledStatus = computed<IntervalsSyncStatusEnabled | null>(() => {
  const data = statusQuery.data.value
  return data?.enabled ? data : null
})

const isBusy = computed(
  () =>
    requestMutation.isPending.value || isPolling.value || enabledStatus.value?.state === 'running',
)

function formatTimestamp(timestamp: string | null): string | null {
  if (!timestamp) {
    return null
  }
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) {
    return null
  }
  return new Intl.DateTimeFormat(locale.value, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

const formattedLastSync = computed<string>(() => {
  const current = enabledStatus.value
  if (!current) {
    return ''
  }
  const timestamp = current.last_finished_at ?? current.last_started_at
  const result = current.last_result
  if (!timestamp && !result) {
    return t('activities.intervalsSync.noRecord')
  }
  const resultText = result ? t(RESULT_LABEL_KEYS[result]) : ''
  const timeText = formatTimestamp(timestamp)
  if (!timeText) {
    return resultText || t('activities.intervalsSync.noRecord')
  }
  if (!resultText) {
    return t('activities.intervalsSync.noRecord')
  }
  return t('activities.intervalsSync.lastSync', { time: timeText, result: resultText })
})

const formattedLastDelete = computed<string>(() => {
  const current = enabledStatus.value
  if (!current) {
    return ''
  }
  const lastDelete = current.last_delete ?? null
  if (lastDelete) {
    const resultText = t(DELETE_RESULT_LABEL_KEYS[lastDelete.result])
    const timeText = formatTimestamp(lastDelete.finished_at ?? lastDelete.requested_at)
    if (timeText) {
      return t('activities.intervalsSync.lastDelete', { time: timeText, result: resultText })
    }
    return t('activities.intervalsSync.lastDeleteNoTime', { result: resultText })
  }
  if ((current.pending_deletes ?? 0) > 0) {
    return t('activities.intervalsSync.lastDeleteNoTime', {
      result: t('activities.intervalsSync.deleteResults.pending'),
    })
  }
  return ''
})

const showPendingDeleteNote = computed<boolean>(() => {
  const current = enabledStatus.value
  if (!current) {
    return false
  }
  return Boolean(
    (current.pending_deletes ?? 0) > 0 &&
    current.last_delete &&
    current.last_delete.result !== 'pending',
  )
})

const feedbackText = computed<string>(() => {
  if (!feedback.value) {
    return ''
  }
  return t(`activities.intervalsSync.feedback.${feedback.value}`)
})

const isFeedbackError = computed(() => feedback.value !== null && feedback.value !== 'requested')

function stopPolling(): void {
  isPolling.value = false
  if (pollTimeoutHandle !== undefined) {
    clearTimeout(pollTimeoutHandle)
    pollTimeoutHandle = undefined
  }
}

function startPolling(): void {
  stopPolling()
  pollBaselineUpdatedAt = statusQuery.dataUpdatedAt.value
  isPolling.value = true
  pollTimeoutHandle = setTimeout(() => {
    stopPolling()
  }, INTERVALS_SYNC_POLL_TIMEOUT_MS)
}

watch(
  () => statusQuery.dataUpdatedAt.value,
  (updatedAt) => {
    if (!isPolling.value || updatedAt <= pollBaselineUpdatedAt) {
      return
    }
    const current = enabledStatus.value
    if (current && current.state === 'idle' && !current.request_pending) {
      stopPolling()
      feedback.value = null
      void queryClient.invalidateQueries({ queryKey: queryKeys.activities.all() })
    }
  },
)

onBeforeUnmount(() => {
  stopPolling()
})

async function handleSync(): Promise<void> {
  if (isBusy.value) {
    return
  }
  feedback.value = null
  try {
    await requestMutation.mutateAsync()
    feedback.value = 'requested'
    startPolling()
  } catch (error: unknown) {
    if (
      error instanceof HttpError &&
      (error.type === 'urn:endurain:error:conflict' || error.status === 409)
    ) {
      if (error.detail === 'running') {
        feedback.value = 'conflictRunning'
        return
      }
      if (error.detail === 'recent') {
        feedback.value = 'conflictRecent'
        return
      }
    }
    feedback.value = 'requestFailed'
  }
}
</script>

<template>
  <Card v-if="enabledStatus" class="flex flex-col gap-2.5">
    <h2 class="text-sm font-semibold text-foreground">
      {{ t('activities.intervalsSync.title') }}
    </h2>

    <div class="flex flex-col gap-1">
      <p class="text-xs text-foreground">{{ formattedLastSync }}</p>
      <p v-if="formattedLastDelete" class="text-xs text-muted-foreground">
        {{ formattedLastDelete }}
      </p>
      <p v-if="showPendingDeleteNote" class="text-xs text-muted-foreground">
        {{ t('activities.intervalsSync.pendingDeletes') }}
      </p>
      <p class="text-xs text-muted-foreground">
        {{ t('activities.intervalsSync.scheduleHint') }}
      </p>
    </div>

    <Button
      type="button"
      variant="outline"
      size="sm"
      class="w-full"
      :disabled="isBusy"
      @click="handleSync"
    >
      <RefreshCw :class="['size-4', isBusy && 'animate-spin']" aria-hidden="true" />
      {{ isBusy ? t('activities.intervalsSync.syncing') : t('activities.intervalsSync.syncNow') }}
    </Button>

    <p
      v-if="feedbackText"
      role="status"
      aria-live="polite"
      :class="['text-xs', isFeedbackError ? 'text-destructive' : 'text-muted-foreground']"
    >
      {{ feedbackText }}
    </p>
  </Card>
</template>
