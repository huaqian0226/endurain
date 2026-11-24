<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ApiKey, ApiKeyTempScopesInput } from '@/features/security/types'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { FormDialog } from '@/components/ui/form-dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { API_KEY_SCOPES } from '@/features/security/services/security'

const MIN_DURATION_MINUTES = 1
const MAX_DURATION_MINUTES = 10080

type DurationPreset = 15 | 60 | 360 | 1440 | 'custom'
type CustomUnit = 'minutes' | 'hours'

const open = defineModel<boolean>('open', { required: true })

const props = defineProps<{
  /** The active API key being temporarily elevated. */
  apiKey: ApiKey | null
  /** Whether the elevation request is in flight. */
  pending: boolean
}>()

const emit = defineEmits<{
  submit: [input: ApiKeyTempScopesInput]
}>()

const { t } = useI18n()

const selectedScopes = ref<string[]>([])
const preset = ref<DurationPreset>(60)
const customValue = ref('60')
const customUnit = ref<CustomUnit>('minutes')

const baseScopes = computed(() => new Set(props.apiKey?.scopes ?? []))

const presets = computed<Array<{ value: DurationPreset; label: string }>>(() => [
  { value: 15, label: t('settings.security.apiKeys.tempAccessPreset15m') },
  { value: 60, label: t('settings.security.apiKeys.tempAccessPreset1h') },
  { value: 360, label: t('settings.security.apiKeys.tempAccessPreset6h') },
  { value: 1440, label: t('settings.security.apiKeys.tempAccessPreset24h') },
  { value: 'custom', label: t('settings.security.apiKeys.tempAccessCustom') },
])

const resolvedDurationMinutes = computed<number | null>(() => {
  if (preset.value !== 'custom') {
    return preset.value
  }
  const parsed = Number(customValue.value)
  if (!Number.isFinite(parsed) || !Number.isInteger(parsed)) {
    return null
  }
  const minutes = customUnit.value === 'hours' ? parsed * 60 : parsed
  if (minutes < MIN_DURATION_MINUTES || minutes > MAX_DURATION_MINUTES) {
    return null
  }
  return minutes
})

const canSubmit = computed(
  () =>
    props.apiKey !== null &&
    selectedScopes.value.length > 0 &&
    resolvedDurationMinutes.value !== null,
)

function toggleScope(scope: string, checked: boolean): void {
  if (baseScopes.value.has(scope)) {
    return
  }
  selectedScopes.value = checked
    ? [...new Set([...selectedScopes.value, scope])]
    : selectedScopes.value.filter((item) => item !== scope)
}

function onCheckboxChange(scope: string, event: Event): void {
  const target = event.target as HTMLInputElement
  toggleScope(scope, target.checked)
}

watch(
  [open, () => props.apiKey],
  ([isOpen, key]) => {
    if (isOpen && key) {
      const base = new Set(key.scopes)
      selectedScopes.value = key.tempScopes.filter((scope) => !base.has(scope))
      preset.value = 60
      customValue.value = '60'
      customUnit.value = 'minutes'
    }
  },
  { immediate: true },
)

function onSubmit(): void {
  if (!props.apiKey || resolvedDurationMinutes.value === null) {
    return
  }
  emit('submit', {
    id: props.apiKey.id,
    scopes: selectedScopes.value,
    durationMinutes: resolvedDurationMinutes.value,
  })
}
</script>

<template>
  <FormDialog
    v-model:open="open"
    :title="t('settings.security.apiKeys.tempAccessTitle')"
    :description="
      t('settings.security.apiKeys.tempAccessDescription', { name: apiKey?.name ?? '' })
    "
    :submit-label="t('settings.security.apiKeys.tempAccessGrant')"
    :cancel-label="t('settings.security.cancel')"
    :close-label="t('settings.security.close')"
    :submitting="pending"
    :can-submit="canSubmit"
    @submit="onSubmit"
  >
    <div class="flex flex-col gap-4">
      <div class="flex flex-col gap-2">
        <Label>{{ t('settings.security.apiKeys.tempAccessScopes') }}</Label>
        <div class="flex flex-col gap-1.5">
          <label
            v-for="scope in API_KEY_SCOPES"
            :key="scope"
            class="flex items-center justify-between gap-2 rounded-input border border-border px-3 py-2 text-sm"
            :class="baseScopes.has(scope) ? 'bg-muted/40 text-muted-foreground' : 'cursor-pointer'"
          >
            <span class="flex items-center gap-2">
              <input
                type="checkbox"
                class="size-4 accent-primary"
                :value="scope"
                :checked="baseScopes.has(scope) || selectedScopes.includes(scope)"
                :disabled="pending || baseScopes.has(scope)"
                @change="(event) => onCheckboxChange(scope, event)"
              />
              <span class="font-mono text-sm">{{ scope }}</span>
            </span>
            <Badge v-if="baseScopes.has(scope)" variant="secondary">
              {{ t('settings.security.apiKeys.tempAccessIncluded') }}
            </Badge>
          </label>
        </div>
        <p class="text-hint">{{ t('settings.security.apiKeys.tempAccessScopesHint') }}</p>
      </div>

      <div class="flex flex-col gap-2">
        <Label>{{ t('settings.security.apiKeys.tempAccessDuration') }}</Label>
        <div class="flex flex-wrap gap-2">
          <Button
            v-for="option in presets"
            :key="String(option.value)"
            type="button"
            size="sm"
            :variant="preset === option.value ? 'default' : 'outline'"
            :disabled="pending"
            @click="preset = option.value"
          >
            {{ option.label }}
          </Button>
        </div>

        <div v-if="preset === 'custom'" class="mt-1 flex items-center gap-2">
          <Input
            id="apikey-temp-custom-duration"
            v-model="customValue"
            type="number"
            min="1"
            :max="customUnit === 'hours' ? 168 : 10080"
            step="1"
            :aria-label="t('settings.security.apiKeys.tempAccessCustomValue')"
            :disabled="pending"
            class="w-28"
          />
          <div class="flex gap-1">
            <Button
              type="button"
              size="sm"
              :variant="customUnit === 'minutes' ? 'default' : 'outline'"
              :disabled="pending"
              @click="customUnit = 'minutes'"
            >
              {{ t('settings.security.apiKeys.tempAccessUnitMinutes') }}
            </Button>
            <Button
              type="button"
              size="sm"
              :variant="customUnit === 'hours' ? 'default' : 'outline'"
              :disabled="pending"
              @click="customUnit = 'hours'"
            >
              {{ t('settings.security.apiKeys.tempAccessUnitHours') }}
            </Button>
          </div>
        </div>
        <p class="text-hint">{{ t('settings.security.apiKeys.tempAccessDurationHint') }}</p>
      </div>
    </div>
  </FormDialog>
</template>
