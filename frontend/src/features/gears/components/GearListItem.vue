<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Pencil, Trash2 } from '@lucide/vue'

import type { Gear } from '@/features/gears/types'
import type { Schemas } from '@/types'

import GearTypeIcon from '@/features/gears/components/GearTypeIcon.vue'
import GearBadges from '@/features/gears/components/GearBadges.vue'
import { Button } from '@/components/ui/button'
import { metersToDisplayDistance } from '@/features/gears/utils/format'
import { gearDistanceMeters } from '@/features/gears/utils/gearGroups'
import { GEAR_TYPE, presentGearType } from '@/features/gears/utils/gearType'

const props = withDefaults(
  defineProps<{
    gear: Gear
    units?: Schemas['Units']
  }>(),
  { units: 'metric' },
)
const emit = defineEmits<{ edit: [gear: Gear]; delete: [gear: Gear] }>()

const { t } = useI18n()

const typeLabel = computed(() => t(presentGearType(props.gear.gearType).labelKey))
const distanceUnitLabel = computed(() =>
  props.units === 'imperial' ? t('gears.unitMi') : t('gears.unitKm'),
)
const distanceLabel = computed(() => {
  if (
    props.gear.gearType === GEAR_TYPE.RACQUET ||
    (props.gear.totalDistance === null && props.gear.initialKms === null)
  ) {
    return null
  }
  const value = metersToDisplayDistance(gearDistanceMeters(props.gear), props.units)
  return `${value} ${distanceUnitLabel.value}`
})
</script>

<template>
  <div class="flex items-center justify-between gap-3 px-4 py-3">
    <div class="flex min-w-0 items-center gap-3">
      <span
        class="flex size-10 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground"
      >
        <GearTypeIcon :type="gear.gearType" class="size-7" />
      </span>
      <div class="min-w-0">
        <RouterLink
          :to="{ name: 'gear', params: { id: gear.id } }"
          class="block truncate font-medium text-foreground hover:underline"
        >
          {{ gear.nickname }}
        </RouterLink>
        <div class="flex flex-wrap items-center gap-2">
          <p class="truncate text-hint">{{ typeLabel }}</p>
          <span
            v-if="distanceLabel"
            data-testid="gear-item-distance"
            class="text-hint tabular-nums"
          >
            {{ distanceLabel }}
          </span>
          <GearBadges :gear="gear" />
        </div>
      </div>
    </div>
    <div class="flex shrink-0 items-center gap-1">
      <Button
        variant="ghost"
        size="icon-sm"
        :aria-label="t('gears.actions.edit')"
        @click="emit('edit', gear)"
      >
        <Pencil class="size-4" aria-hidden="true" />
      </Button>
      <Button
        variant="ghostDestructive"
        size="icon-sm"
        :aria-label="t('gears.actions.delete')"
        @click="emit('delete', gear)"
      >
        <Trash2 class="size-4" aria-hidden="true" />
      </Button>
    </div>
  </div>
</template>
