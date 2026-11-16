<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Activity, ActivityEditInput } from '@/features/activities/types'

import { FormDialog } from '@/components/ui/form-dialog'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { inputFieldClass } from '@/components/ui/input'
import { MarkdownEditor } from '@/components/ui/markdown-editor'
import { Switch } from '@/components/ui/switch'
import { HttpError } from '@/services/http'
import { useToasts } from '@/composables/useToasts'
import {
  useEditActivityMutation,
  useActivityGearOptionsQuery,
  useEquipmentCandidatesQuery,
} from '@/features/activities/composables/useActivityDetail'
import {
  ACTIVITY_TYPE_LABEL_KEYS,
  activityTypeToGearType,
} from '@/features/activities/utils/activityType'
import { Button } from '@/components/ui/button'

const props = defineProps<{
  /** The activity being edited; seeds the form whenever the dialog opens. */
  activity: Activity
}>()

const open = defineModel<boolean>('open', { required: true })

const { t } = useI18n()
const toasts = useToasts()

const editMutation = useEditActivityMutation()
const isSaving = computed(() => editMutation.isPending.value)

/** Projects an activity onto the editable form values. */
function toFormValues(activity: Activity): ActivityEditInput {
  return {
    gearId: activity.gearId,
    equipmentSelection: {
      confirmed: activity.equipmentConfirmed ?? false,
      items: (activity.equipment ?? []).map((item) => ({ ...item })),
    },
    name: activity.name,
    activityType: activity.activityType,
    description: activity.description ?? '',
    privateNotes: activity.privateNotes ?? '',
    visibility: activity.visibility,
    isHidden: activity.isHidden,
    hideStartTime: activity.privacy.hideStartTime,
    hideLocation: activity.privacy.hideLocation,
    hideMap: activity.privacy.hideMap,
    hideHr: activity.privacy.hideHr,
    hidePower: activity.privacy.hidePower,
    hideCadence: activity.privacy.hideCadence,
    hideElevation: activity.privacy.hideElevation,
    hideSpeed: activity.privacy.hideSpeed,
    hidePace: activity.privacy.hidePace,
    hideLaps: activity.privacy.hideLaps,
    hideWorkoutSetsSteps: activity.privacy.hideWorkoutSetsSteps,
    hideGear: activity.privacy.hideGear,
  }
}

const form = reactive<ActivityEditInput>(toFormValues(props.activity))
const editBaseline = ref({ id: props.activity.id, version: props.activity.version })
const equipmentChanged = ref(false)
const equipmentQuery = useEquipmentCandidatesQuery(open)
const gearOptions = useActivityGearOptionsQuery(
  computed(() => activityTypeToGearType(form.activityType)),
)
const selectedEquipment = computed(() => form.equipmentSelection?.items ?? [])

/** Changes an explicit actual-use selection, never a default equipment suggestion. */
function setEquipment(assetId: string, mode: string): void {
  const items = selectedEquipment.value.filter((item) => item.asset_id !== assetId)
  if (mode === 'carried' || mode === 'used') items.push({ asset_id: assetId, use_mode: mode })
  form.equipmentSelection = { confirmed: true, items }
  equipmentChanged.value = true
}

/** Records whether the owner has confirmed the complete selection. */
function confirmEquipment(value: boolean): void {
  form.equipmentSelection = { confirmed: value, items: value ? selectedEquipment.value : [] }
  equipmentChanged.value = true
}

const equipmentRows = computed(() => {
  const rows = [...(equipmentQuery.data.value?.items ?? [])]
  for (const item of selectedEquipment.value) {
    if (!rows.some((row) => row.asset_id === item.asset_id)) {
      rows.push({
        asset_id: item.asset_id,
        label: t('activities.equipment.unavailableItem', { id: item.asset_id }),
        status: 'retired',
      })
    }
  }
  return rows
})

// Re-seed the form from the activity each time the dialog opens, so reopening
// after a cache update (or cancel) starts from the server-authoritative values.
watch(open, (isOpen) => {
  if (isOpen) {
    Object.assign(form, toFormValues(props.activity))
    editBaseline.value = { id: props.activity.id, version: props.activity.version }
    equipmentChanged.value = false
  }
})

/** Activity-type options, sorted by code, for the type selector. */
const activityTypeOptions = computed(() =>
  Object.entries(ACTIVITY_TYPE_LABEL_KEYS)
    .map(([value, labelKey]) => ({ value: Number(value), labelKey }))
    .sort((a, b) => a.value - b.value),
)

const visibilityOptions = [
  { value: 0, labelKey: 'activities.visibility.public' },
  { value: 1, labelKey: 'activities.visibility.followers' },
  { value: 2, labelKey: 'activities.visibility.private' },
]

/** The per-metric "hide from others" toggles, mirroring v1's edit modal. */
const privacyFields = [
  { key: 'hideStartTime', labelKey: 'activities.edit.hideStartTime' },
  { key: 'hideLocation', labelKey: 'activities.edit.hideLocation' },
  { key: 'hideMap', labelKey: 'activities.edit.hideMap' },
  { key: 'hideHr', labelKey: 'activities.edit.hideHr' },
  { key: 'hidePower', labelKey: 'activities.edit.hidePower' },
  { key: 'hideCadence', labelKey: 'activities.edit.hideCadence' },
  { key: 'hideElevation', labelKey: 'activities.edit.hideElevation' },
  { key: 'hideSpeed', labelKey: 'activities.edit.hideSpeed' },
  { key: 'hidePace', labelKey: 'activities.edit.hidePace' },
  { key: 'hideLaps', labelKey: 'activities.edit.hideLaps' },
  { key: 'hideWorkoutSetsSteps', labelKey: 'activities.edit.hideWorkoutSetsSteps' },
  { key: 'hideGear', labelKey: 'activities.edit.hideGear' },
] as const

const canSubmit = computed(() => form.name.trim().length > 0)

/** Persists the edited fields, then closes the dialog. */
async function submit(): Promise<void> {
  if (!canSubmit.value) {
    return
  }
  try {
    await editMutation.mutateAsync({
      id: editBaseline.value.id,
      input: {
        ...form,
        equipmentSelection: equipmentChanged.value ? form.equipmentSelection : undefined,
      },
      version: editBaseline.value.version,
    })
    open.value = false
    toasts.success(t('activities.edit.success'))
  } catch (error) {
    // 412 is not a failure to save, it is a refusal to overwrite: the form was
    // built from a copy that someone else has since changed. Saying so lets the
    // user reopen the (now refreshed) activity instead of retrying blindly.
    if (error instanceof HttpError && error.type === 'urn:endurain:error:precondition-failed') {
      open.value = false
      toasts.error(t('activities.edit.staleError'))
      return
    }
    toasts.error(t('activities.edit.error'))
  }
}
</script>

<template>
  <FormDialog
    v-model:open="open"
    :title="t('activities.edit.title')"
    :submit-label="t('activities.edit.save')"
    :cancel-label="t('activities.edit.cancel')"
    :close-label="t('activities.edit.close')"
    :submitting="isSaving"
    :can-submit="canSubmit"
    content-class="sm:max-w-2xl"
    @submit="submit"
  >
    <div class="flex flex-col gap-3">
      <FormField :label="t('activities.edit.name')">
        <template #default="{ fieldId }">
          <Input
            :id="fieldId"
            v-model="form.name"
            class="w-full"
            :maxlength="45"
            :disabled="isSaving"
          />
        </template>
      </FormField>

      <FormField :label="t('activities.edit.type')">
        <template #default="{ fieldId }">
          <select
            :id="fieldId"
            v-model="form.activityType"
            :class="[inputFieldClass, 'w-full']"
            :disabled="isSaving"
          >
            <option v-for="opt in activityTypeOptions" :key="opt.value" :value="opt.value">
              {{ t(opt.labelKey) }}
            </option>
          </select>
        </template>
      </FormField>

      <FormField :label="t('activities.equipment.primaryGear')">
        <template #default="{ fieldId }">
          <select
            :id="fieldId"
            v-model="form.gearId"
            :class="[inputFieldClass, 'w-full']"
            :disabled="isSaving"
          >
            <option :value="null">{{ t('activities.equipment.noPrimaryGear') }}</option>
            <option
              v-if="form.gearId && !gearOptions.data.value?.some((gear) => gear.id === form.gearId)"
              :value="form.gearId"
            >
              {{ t('activities.equipment.currentGear', { id: form.gearId }) }}
            </option>
            <option v-for="gear in gearOptions.data.value ?? []" :key="gear.id" :value="gear.id">
              {{ gear.nickname }}
            </option>
          </select>
          <p v-if="gearOptions.isError.value" class="text-field-error">
            {{ t('activities.equipment.loadError') }}
          </p>
        </template>
      </FormField>

      <fieldset
        class="flex flex-col gap-3 border-t border-border pt-4"
        :disabled="isSaving"
        :aria-busy="equipmentQuery.isFetching.value"
      >
        <legend class="text-section-heading">{{ t('activities.equipment.title') }}</legend>
        <p class="text-caption text-muted-foreground">{{ t('activities.equipment.help') }}</p>
        <p v-if="equipmentQuery.isLoading.value">{{ t('activities.equipment.loading') }}</p>
        <div v-else-if="equipmentQuery.isError.value" role="status">
          <p class="text-field-error">{{ t('activities.equipment.loadError') }}</p>
          <Button type="button" variant="outline" size="sm" @click="equipmentQuery.refetch()">{{
            t('activities.equipment.retry')
          }}</Button>
        </div>
        <p v-else-if="!equipmentRows.length" class="text-caption">
          {{ t('activities.equipment.empty') }}
        </p>
        <FormField v-for="item in equipmentRows" :key="item.asset_id" :label="item.label">
          <template #default="{ fieldId }">
            <select
              :id="fieldId"
              :class="[inputFieldClass, 'w-full']"
              :value="
                selectedEquipment.find((selected) => selected.asset_id === item.asset_id)
                  ?.use_mode ?? ''
              "
              :disabled="isSaving || equipmentQuery.isError.value"
              @change="setEquipment(item.asset_id, ($event.target as HTMLSelectElement).value)"
            >
              <option value="">{{ t('activities.equipment.notSelected') }}</option>
              <option value="carried">{{ t('activities.equipment.carried') }}</option>
              <option value="used">{{ t('activities.equipment.used') }}</option>
            </select>
          </template>
        </FormField>
        <Switch
          :model-value="form.equipmentSelection?.confirmed ?? false"
          :disabled="isSaving || equipmentQuery.isError.value"
          @update:model-value="confirmEquipment"
          >{{ t('activities.equipment.confirmed') }}</Switch
        >
        <p class="text-caption" aria-live="polite">
          {{
            form.equipmentSelection?.confirmed
              ? t('activities.equipment.confirmedState')
              : t('activities.equipment.unknownState')
          }}
        </p>
      </fieldset>

      <FormField :label="t('activities.edit.description')">
        <template #default="{ fieldId }">
          <MarkdownEditor
            :id="fieldId"
            v-model="form.description"
            :rows="3"
            :maxlength="2500"
            :disabled="isSaving"
          />
        </template>
      </FormField>

      <FormField :label="t('activities.edit.privateNotes')">
        <template #default="{ fieldId }">
          <MarkdownEditor
            :id="fieldId"
            v-model="form.privateNotes"
            :rows="3"
            :maxlength="2500"
            :disabled="isSaving"
          />
        </template>
      </FormField>

      <FormField :label="t('activities.edit.visibility')">
        <template #default="{ fieldId }">
          <select
            :id="fieldId"
            v-model="form.visibility"
            :class="[inputFieldClass, 'w-full']"
            :disabled="isSaving"
          >
            <option v-for="opt in visibilityOptions" :key="opt.value" :value="opt.value">
              {{ t(opt.labelKey) }}
            </option>
          </select>
        </template>
      </FormField>

      <Switch v-model="form.isHidden" :disabled="isSaving">{{
        t('activities.edit.isHidden')
      }}</Switch>

      <div class="flex flex-col gap-2 border-t border-border pt-4">
        <p class="text-caption">{{ t('activities.edit.privacyTitle') }}</p>
        <div class="grid grid-cols-1 gap-x-6 sm:grid-cols-2">
          <Switch
            v-for="field in privacyFields"
            :key="field.key"
            v-model="form[field.key]"
            :disabled="isSaving"
          >
            {{ t(field.labelKey) }}
          </Switch>
        </div>
      </div>
    </div>
  </FormDialog>
</template>
