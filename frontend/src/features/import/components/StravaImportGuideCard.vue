<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { BookOpen, ChevronDown } from '@lucide/vue'

import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'

const props = withDefaults(
  defineProps<{
    /** Whether the guide starts expanded. */
    defaultOpen?: boolean
  }>(),
  { defaultOpen: true },
)

const { t } = useI18n()
const isOpen = ref(props.defaultOpen)

const keyFiles = [
  { name: 'bikes.csv', descKey: 'settings.import.stravaGuide.fileBikes' },
  { name: 'shoes.csv', descKey: 'settings.import.stravaGuide.fileShoes' },
  { name: 'activities.csv', descKey: 'settings.import.stravaGuide.fileActivitiesCsv' },
  { name: 'activities/', descKey: 'settings.import.stravaGuide.fileActivitiesDir' },
  { name: 'media/', descKey: 'settings.import.stravaGuide.fileMediaDir' },
] as const
</script>

<template>
  <Card class="flex flex-col gap-3">
    <button
      type="button"
      class="flex w-full items-center justify-between gap-3 text-left"
      :aria-expanded="isOpen"
      aria-controls="strava-import-guide-body"
      @click="isOpen = !isOpen"
    >
      <div class="flex min-w-0 items-center gap-3">
        <div
          class="flex size-10 shrink-0 items-center justify-center rounded-full bg-muted-foreground/15 text-muted-foreground"
        >
          <BookOpen class="size-5" aria-hidden="true" />
        </div>
        <div class="min-w-0">
          <h2 class="text-card-heading">{{ t('settings.import.stravaGuide.title') }}</h2>
          <p class="text-hint">{{ t('settings.import.stravaGuide.subtitle') }}</p>
        </div>
      </div>

      <span class="inline-flex shrink-0 items-center gap-1 text-sm text-muted-foreground">
        <span>
          {{
            isOpen
              ? t('settings.import.stravaGuide.toggleHide')
              : t('settings.import.stravaGuide.toggleShow')
          }}
        </span>
        <ChevronDown
          class="size-4 transition-transform"
          :class="isOpen ? 'rotate-180' : ''"
          aria-hidden="true"
        />
      </span>
    </button>

    <div
      v-if="isOpen"
      id="strava-import-guide-body"
      class="flex flex-col gap-4 border-t border-border pt-3 text-sm"
    >
      <!-- 1. What to download -->
      <section class="flex flex-col gap-2">
        <h3 class="font-medium text-foreground">
          {{ t('settings.import.stravaGuide.downloadTitle') }}
        </h3>
        <p class="text-body">
          {{ t('settings.import.stravaGuide.downloadPath') }}
        </p>
        <p class="text-hint">
          {{ t('settings.import.stravaGuide.downloadFilesIntro') }}
        </p>
        <ul class="flex flex-col gap-1.5 rounded-input border border-border bg-muted/30 p-3">
          <li v-for="item in keyFiles" :key="item.name" class="flex flex-wrap items-baseline gap-2">
            <code class="rounded bg-muted-foreground/15 px-1.5 py-0.5 font-mono text-xs">
              {{ item.name }}
            </code>
            <span class="text-muted-foreground">{{ t(item.descKey) }}</span>
          </li>
        </ul>
      </section>

      <!-- 2. Recommended order -->
      <section class="flex flex-col gap-2.5">
        <h3 class="font-medium text-foreground">
          {{ t('settings.import.stravaGuide.orderTitle') }}
        </h3>

        <div class="flex flex-col gap-2 rounded-input border border-border p-3">
          <div class="flex items-center gap-2">
            <Badge variant="secondary">{{ t('settings.import.stravaGuide.step1Badge') }}</Badge>
            <span class="font-medium text-foreground">
              {{ t('settings.import.stravaGuide.step1Title') }}
            </span>
          </div>
          <p class="text-body">{{ t('settings.import.stravaGuide.step1Body') }}</p>
          <Alert kind="warning">
            {{ t('settings.import.stravaGuide.step1MatchWarning') }}
          </Alert>
        </div>

        <div class="flex flex-col gap-2 rounded-input border border-border p-3">
          <div class="flex items-center gap-2">
            <Badge variant="secondary">{{ t('settings.import.stravaGuide.step2Badge') }}</Badge>
            <span class="font-medium text-foreground">
              {{ t('settings.import.stravaGuide.step2Title') }}
            </span>
          </div>
          <p class="text-body">{{ t('settings.import.stravaGuide.step2Body') }}</p>
        </div>
      </section>

      <!-- 3. Notes -->
      <section class="flex flex-col gap-2">
        <h3 class="font-medium text-foreground">
          {{ t('settings.import.stravaGuide.notesTitle') }}
        </h3>
        <ul class="list-disc space-y-1 pl-5 text-muted-foreground">
          <li>{{ t('settings.import.stravaGuide.noteLanguages') }}</li>
          <li>{{ t('settings.import.stravaGuide.noteMissingGear') }}</li>
          <li>{{ t('settings.import.stravaGuide.noteNotImported') }}</li>
          <li>{{ t('settings.import.stravaGuide.noteBackground') }}</li>
        </ul>
      </section>
    </div>
  </Card>
</template>
