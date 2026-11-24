<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Gear } from '@/features/gears/types'

import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { parseIsoDate } from '@/utils/datetime'

/**
 * Displays a gear's rich profile dossier on the detail page: retirement status
 * badge (with date when set) and a definition list of populated profile fields.
 * Empty fields are hidden, dates follow the viewer's locale, and multiline text
 * (`specs`, `notes`) is rendered strictly as escaped plain text with preserved
 * line breaks (never `v-html`).
 */
const props = defineProps<{
  /** The gear whose profile fields are shown. */
  gear: Gear
}>()

const { t, locale } = useI18n()

/** Formats a `YYYY-MM-DD` calendar date in the active locale without timezone drift. */
function formatCalendarDate(iso: string | null): string | null {
  if (!iso) {
    return null
  }
  const date = parseIsoDate(iso.slice(0, 10))
  return Number.isNaN(date.getTime())
    ? null
    : new Intl.DateTimeFormat(locale.value, { dateStyle: 'medium', timeZone: 'UTC' }).format(date)
}

const purchaseDateLabel = computed(() => formatCalendarDate(props.gear.purchaseDate))
const retiredDateLabel = computed(() => formatCalendarDate(props.gear.retiredDate))

const isRetired = computed(() => !props.gear.active || props.gear.retiredDate !== null)
const retiredBadgeText = computed(() =>
  retiredDateLabel.value
    ? t('gears.profile.retiredBadgeWithDate', { date: retiredDateLabel.value })
    : t('gears.profile.retiredBadge'),
)

const hasProfileDetails = computed(() =>
  Boolean(
    purchaseDateLabel.value ||
    retiredDateLabel.value ||
    props.gear.modelYear !== null ||
    props.gear.size ||
    props.gear.color ||
    props.gear.frameNumber ||
    props.gear.groupset ||
    props.gear.purchaseSource ||
    props.gear.specs ||
    props.gear.notes,
  ),
)
</script>

<template>
  <Card padding="none" class="divide-y divide-border overflow-hidden">
    <div class="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
      <h2 class="text-card-heading">{{ t('gears.profile.title') }}</h2>
      <Badge v-if="isRetired" variant="destructive">
        {{ retiredBadgeText }}
      </Badge>
    </div>
    <div class="px-4 py-3">
      <dl
        v-if="hasProfileDetails"
        class="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-1"
      >
        <div v-if="purchaseDateLabel" class="flex flex-col gap-0.5">
          <dt class="text-hint">{{ t('gears.profile.purchaseDate') }}</dt>
          <dd class="text-body">{{ purchaseDateLabel }}</dd>
        </div>
        <div v-if="retiredDateLabel" class="flex flex-col gap-0.5">
          <dt class="text-hint">{{ t('gears.profile.retiredDate') }}</dt>
          <dd class="text-body">{{ retiredDateLabel }}</dd>
        </div>
        <div v-if="gear.modelYear !== null" class="flex flex-col gap-0.5">
          <dt class="text-hint">{{ t('gears.profile.modelYear') }}</dt>
          <dd class="text-body tabular-nums">{{ gear.modelYear }}</dd>
        </div>
        <div v-if="gear.size" class="flex flex-col gap-0.5">
          <dt class="text-hint">{{ t('gears.profile.size') }}</dt>
          <dd class="text-body">{{ gear.size }}</dd>
        </div>
        <div v-if="gear.color" class="flex flex-col gap-0.5">
          <dt class="text-hint">{{ t('gears.profile.color') }}</dt>
          <dd class="text-body">{{ gear.color }}</dd>
        </div>
        <div v-if="gear.frameNumber" class="flex flex-col gap-0.5">
          <dt class="text-hint">{{ t('gears.profile.frameNumber') }}</dt>
          <dd class="text-body font-mono break-all">{{ gear.frameNumber }}</dd>
        </div>
        <div v-if="gear.groupset" class="flex flex-col gap-0.5">
          <dt class="text-hint">{{ t('gears.profile.groupset') }}</dt>
          <dd class="text-body">{{ gear.groupset }}</dd>
        </div>
        <div v-if="gear.purchaseSource" class="flex flex-col gap-0.5">
          <dt class="text-hint">{{ t('gears.profile.purchaseSource') }}</dt>
          <dd class="text-body">{{ gear.purchaseSource }}</dd>
        </div>
        <div v-if="gear.specs" class="flex flex-col gap-0.5 sm:col-span-2 lg:col-span-1">
          <dt class="text-hint">{{ t('gears.profile.specs') }}</dt>
          <dd data-testid="gear-profile-specs" class="text-body whitespace-pre-wrap break-words">
            {{ gear.specs }}
          </dd>
        </div>
        <div v-if="gear.notes" class="flex flex-col gap-0.5 sm:col-span-2 lg:col-span-1">
          <dt class="text-hint">{{ t('gears.profile.notes') }}</dt>
          <dd data-testid="gear-profile-notes" class="text-body whitespace-pre-wrap break-words">
            {{ gear.notes }}
          </dd>
        </div>
      </dl>
      <p v-else class="text-hint">{{ t('gears.profile.empty') }}</p>
    </div>
  </Card>
</template>
