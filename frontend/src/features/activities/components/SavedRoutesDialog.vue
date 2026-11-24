<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import { FormDialog } from '@/components/ui/form-dialog'
import { FormField } from '@/components/ui/form-field'
import { Select } from '@/components/ui/select'
import { useToasts } from '@/composables/useToasts'
import {
  listSavedRoutes,
  listRouteTrips,
  sendRouteToTrip,
  type SavedRoute,
  type RouteTrip,
} from '@/features/activities/services/savedRoutes'
import { presentActivityType } from '@/features/activities/utils/activityType'

const open = defineModel<boolean>('open', { required: true })
const { t } = useI18n()
const toasts = useToasts()
const routes = ref<SavedRoute[]>([])
const trips = ref<RouteTrip[]>([])
const selectedRoute = ref(0)
const selectedTrip = ref(0)
const route = computed(() => routes.value.find((item) => item.id === selectedRoute.value))
const loading = ref(false)
const sending = ref(false)
const error = ref('')

watch(open, async (visible, _, onCleanup) => {
  if (!visible) return
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  routes.value = []
  trips.value = []
  selectedRoute.value = selectedTrip.value = 0
  error.value = ''
  loading.value = true
  try {
    routes.value = await listSavedRoutes(controller.signal)
    if (routes.value.length) {
      selectedRoute.value = routes.value[0]?.id ?? 0
      trips.value = await listRouteTrips(controller.signal)
      if (trips.value.length === 1) selectedTrip.value = trips.value[0]?.id ?? 0
    }
  } catch {
    if (!controller.signal.aborted) {
      error.value = t(
        routes.value.length ? 'activities.routes.tripsError' : 'activities.routes.loadError',
      )
    }
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
})

async function send(): Promise<void> {
  if (!route.value || !selectedTrip.value || sending.value) return
  const originalCount = route.value.point_count
  sending.value = true
  try {
    const result = await sendRouteToTrip(route.value.id, selectedTrip.value)
    toasts.success(
      t(result.already_added ? 'activities.routes.alreadyAdded' : 'activities.routes.added'),
    )
    if (result.sent_points < originalCount) {
      toasts.info(
        t('activities.routes.sampled', { count: result.sent_points, total: originalCount }),
      )
    }
    open.value = false
  } catch {
    toasts.error(t('activities.routes.sendError'))
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <FormDialog
    v-model:open="open"
    :title="t('activities.routes.library')"
    :submit-label="t('activities.routes.send')"
    :cancel-label="t('activities.edit.cancel')"
    :close-label="t('activities.edit.close')"
    :submitting="sending"
    :can-submit="Boolean(route && selectedTrip && !loading)"
    @submit="send"
  >
    <p v-if="loading" role="status" class="text-body">{{ t('activities.routes.loading') }}</p>
    <div v-else class="flex flex-col gap-4">
      <FormField v-if="routes.length" :label="t('activities.routes.route')">
        <template #default="{ fieldId }">
          <Select :id="fieldId" v-model="selectedRoute" class="w-full" :disabled="sending">
            <option v-for="item in routes" :key="item.id" :value="item.id">
              {{ item.name }} · {{ t(presentActivityType(item.activity_type).labelKey) }}
            </option>
          </Select>
          <p v-if="route" class="mt-1 text-sm text-muted-foreground">
            {{ t('activities.routes.points', { count: route.point_count }) }}
          </p>
        </template>
      </FormField>
      <p v-if="error" role="alert" class="text-sm text-destructive">{{ error }}</p>
      <p v-else-if="!routes.length" class="text-body">{{ t('activities.routes.empty') }}</p>
      <p v-else-if="!trips.length" class="text-body">{{ t('activities.routes.noTrips') }}</p>
      <FormField v-else :label="t('activities.routes.trip')">
        <template #default="{ fieldId }">
          <Select :id="fieldId" v-model="selectedTrip" class="w-full" :disabled="sending">
            <option disabled :value="0">{{ t('activities.routes.selectTrip') }}</option>
            <option v-for="trip in trips" :key="trip.id" :value="trip.id">{{ trip.title }}</option>
          </Select>
        </template>
      </FormField>
    </div>
  </FormDialog>
</template>
