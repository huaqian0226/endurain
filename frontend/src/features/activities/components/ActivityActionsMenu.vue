<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { EllipsisVertical, ImagePlus, Pencil, Route, Trash2 } from '@lucide/vue'

import type { Activity } from '@/features/activities/types'

import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useToasts } from '@/composables/useToasts'
import {
  useDeleteActivityMutation,
  useUploadActivityMediaMutation,
} from '@/features/activities/composables/useActivityDetail'
import {
  useIntervalsActivityQuery,
  useRequestIntervalsDeleteMutation,
} from '@/features/activities/composables/useIntervalsSync'
import { FormDialog } from '@/components/ui/form-dialog'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { HttpError } from '@/services/http'
import {
  saveActivityRoute,
  supportedRouteActivities,
} from '@/features/activities/services/savedRoutes'
import ActivityEditDialog from '@/features/activities/components/ActivityEditDialog.vue'

const props = defineProps<{
  /** The activity these owner-only actions apply to. */
  activity: Activity
}>()

const { t } = useI18n()
const router = useRouter()
const toasts = useToasts()

const routeOpen = ref(false)
const routeName = ref('')
const savingRoute = ref(false)
const routeError = ref('')

function openSaveRoute(): void {
  routeName.value = props.activity.name
  routeError.value = ''
  routeOpen.value = true
}

async function saveRoute(): Promise<void> {
  if (savingRoute.value || !routeName.value.trim()) return
  savingRoute.value = true
  routeError.value = ''
  try {
    const route = await saveActivityRoute(props.activity.id, routeName.value.trim())
    toasts.success(t('activities.routes.saved', { name: route.name }))
    routeOpen.value = false
  } catch (error) {
    routeError.value = t(
      error instanceof HttpError && error.status === 400
        ? 'activities.routes.noGps'
        : 'activities.routes.saveError',
    )
  } finally {
    savingRoute.value = false
  }
}

const deleteMutation = useDeleteActivityMutation()
const deleteIntervalsMutation = useRequestIntervalsDeleteMutation()
const uploadMutation = useUploadActivityMediaMutation(() => props.activity.id)
const isDeleteOpen = ref(false)
const isEditOpen = ref(false)
const alsoDeleteIntervals = ref(false)
const isDeleting = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const intervalsActivityQuery = useIntervalsActivityQuery(() => props.activity.id, isDeleteOpen)

const hasIntervalsId = computed(() =>
  Boolean(!intervalsActivityQuery.isError.value && intervalsActivityQuery.data.value?.intervals_id),
)

watch(isDeleteOpen, () => {
  alsoDeleteIntervals.value = false
})

/** Opens the native file picker for the Add photo action. */
function openFilePicker(): void {
  fileInput.value?.click()
}

/** Uploads the chosen image, resetting the input so the same file re-selects. */
async function onFileSelected(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0] ?? null
  input.value = ''
  if (!file) {
    return
  }
  if (!file.type.startsWith('image/')) {
    toasts.error(t('activities.media.invalidType'))
    return
  }
  try {
    await uploadMutation.mutateAsync(file)
    toasts.success(t('activities.media.uploadSuccess'))
  } catch {
    toasts.error(t('activities.media.uploadError'))
  }
}

/** Deletes the activity (and optionally queues an intervals.icu delete), then returns home. */
async function confirmDelete(): Promise<void> {
  const shouldDeleteIntervals = alsoDeleteIntervals.value && hasIntervalsId.value
  isDeleting.value = true
  try {
    try {
      await deleteMutation.mutateAsync(props.activity.id)
    } catch {
      toasts.error(t('activities.actions.deleteError'))
      return
    }

    isDeleteOpen.value = false
    if (shouldDeleteIntervals) {
      try {
        await deleteIntervalsMutation.mutateAsync(props.activity.id)
        toasts.success(t('activities.actions.deleteSuccessWithIntervals'))
      } catch {
        toasts.warning(t('activities.actions.deleteIntervalsError'))
      }
    } else {
      toasts.success(t('activities.actions.deleteSuccess'))
    }
    await router.push({ name: 'home' })
  } finally {
    isDeleting.value = false
  }
}
</script>

<template>
  <DropdownMenu>
    <DropdownMenuTrigger
      class="flex cursor-pointer items-center rounded-input p-1 text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/30"
      :aria-label="t('activities.actions.menu')"
    >
      <EllipsisVertical class="size-5" />
    </DropdownMenuTrigger>
    <DropdownMenuContent align="end">
      <DropdownMenuItem @select="openFilePicker">
        <ImagePlus class="size-4" />
        <span>{{ t('activities.media.addMedia') }}</span>
      </DropdownMenuItem>
      <DropdownMenuItem
        v-if="supportedRouteActivities.has(activity.activityType)"
        @select="openSaveRoute"
      >
        <Route class="size-4" />
        <span>{{ t('activities.routes.save') }}</span>
      </DropdownMenuItem>
      <DropdownMenuItem @select="isEditOpen = true">
        <Pencil class="size-4" />
        <span>{{ t('activities.actions.edit') }}</span>
      </DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem
        class="text-destructive hover:bg-destructive/10 hover:text-destructive focus:bg-destructive/10 focus:text-destructive data-[highlighted]:bg-destructive/10 data-[highlighted]:text-destructive"
        @select="isDeleteOpen = true"
      >
        <Trash2 class="size-4" />
        <span>{{ t('activities.actions.delete') }}</span>
      </DropdownMenuItem>
    </DropdownMenuContent>
  </DropdownMenu>
  <FormDialog
    v-model:open="routeOpen"
    :title="t('activities.routes.save')"
    :submit-label="t('activities.edit.save')"
    :cancel-label="t('activities.edit.cancel')"
    :close-label="t('activities.edit.close')"
    :can-submit="Boolean(routeName.trim())"
    :submitting="savingRoute"
    @submit="saveRoute"
  >
    <FormField :label="t('activities.routes.name')">
      <template #default="{ fieldId }"
        ><Input
          :id="fieldId"
          v-model="routeName"
          :maxlength="160"
          :disabled="savingRoute"
          class="w-full"
      /></template>
    </FormField>
    <p v-if="routeError" role="alert" class="mt-2 text-sm text-destructive">{{ routeError }}</p>
  </FormDialog>

  <input ref="fileInput" type="file" accept="image/*" class="hidden" @change="onFileSelected" />

  <ActivityEditDialog v-model:open="isEditOpen" :activity="activity" />

  <ConfirmDialog
    v-model:open="isDeleteOpen"
    :title="t('activities.actions.deleteTitle')"
    :description="t('activities.actions.deleteBody', { name: activity.name })"
    :confirm-label="t('activities.actions.delete')"
    :cancel-label="t('activities.actions.cancel')"
    :close-label="t('activities.actions.close')"
    :pending="isDeleting"
    @confirm="confirmDelete"
  >
    <div v-if="hasIntervalsId" class="mt-1 flex flex-col gap-1">
      <label class="flex cursor-pointer items-start gap-2.5 text-sm text-foreground">
        <input
          v-model="alsoDeleteIntervals"
          type="checkbox"
          class="mt-0.5 size-4 shrink-0 rounded border-border accent-destructive focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/30"
          :disabled="isDeleting"
        />
        <span>{{ t('activities.actions.deleteIntervalsLabel') }}</span>
      </label>
      <p class="pl-6.5 text-xs text-muted-foreground">
        {{ t('activities.actions.deleteIntervalsHint') }}
      </p>
    </div>
  </ConfirmDialog>
</template>
