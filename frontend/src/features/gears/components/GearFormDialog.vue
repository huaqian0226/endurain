<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { Gear, GearInput, GearType } from '@/features/gears/types'
import type { Schemas } from '@/types'

import { FormDialog } from '@/components/ui/form-dialog'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { inputFieldClass } from '@/components/ui/input/fieldClasses'
import { useForm } from '@/composables/useForm'
import { HttpError } from '@/services/http'
import { todayIsoDate } from '@/utils/datetime'
import { toNumberOrNull } from '@/utils/number'
import { kmToMiles, milesToKm } from '@/utils/units'
import { compose, maxLength, required } from '@/utils/validators'
import { currencySymbol } from '@/features/gears/utils/format'
import { GEAR_TYPE, GEAR_TYPE_VALUES, presentGearType } from '@/features/gears/utils/gearType'
import { useCreateGearMutation, useUpdateGearMutation } from '@/features/gears/composables/useGears'

const open = defineModel<boolean>('open', { required: true })

const props = withDefaults(
  defineProps<{
    /** The gear being edited, or `null`/absent when adding a new one. */
    gear?: Gear | null
    /** The viewer's measurement system, used for the distance field unit. */
    units: Schemas['Units']
    /** The viewer's currency, used for the purchase-value symbol. */
    currency: Schemas['Currency']
  }>(),
  { gear: null },
)

const emit = defineEmits<{
  success: [message: string]
  error: [message: string]
}>()

const { t } = useI18n()

const createMutation = useCreateGearMutation()
const updateMutation = useUpdateGearMutation()

/** Form shape: numeric/date fields are kept as strings and parsed at submit. */
interface GearFormValues {
  nickname: string
  gearType: GearType
  brand: string
  model: string
  active: boolean
  createdAt: string
  initialDistance: string
  purchaseValue: string
  purchaseDate: string
  retiredDate: string
  frameNumber: string
  size: string
  color: string
  modelYear: string
  groupset: string
  specs: string
  purchaseSource: string
  notes: string
}

const NICKNAME_MAX = 250
const FRAME_NUMBER_MAX = 100
const SIZE_MAX = 50
const COLOR_MAX = 100
const GROUPSET_MAX = 250
const PURCHASE_SOURCE_MAX = 250
const SPECS_MAX = 4000
const NOTES_MAX = 8000
const MODEL_YEAR_MIN = 1900
const MODEL_YEAR_MAX = 2100

/** Trims a string and returns `null` when empty or whitespace-only. */
function cleanOptionalText(value: string): string | null {
  const trimmed = value.trim()
  return trimmed.length > 0 ? trimmed : null
}

/** Parses an optional integer model year, returning `null` when blank or invalid. */
function parseModelYear(value: string | number): number | null {
  const trimmed = String(value ?? '').trim()
  if (!trimmed || !/^\d+$/.test(trimmed)) {
    return null
  }
  const parsed = Number.parseInt(trimmed, 10)
  return Number.isSafeInteger(parsed) ? parsed : null
}

/** Renders a stored km distance in the viewer's units for the form input. */
function displayDistanceFromKm(km: number | null): string {
  if (km === null) {
    return ''
  }
  const value = props.units === 'imperial' ? kmToMiles(km) : km
  return String(Math.round(value * 100) / 100)
}

/** The pristine values used for "add" and as the reset baseline. */
function defaultValues(): GearFormValues {
  return {
    nickname: '',
    gearType: GEAR_TYPE.BICYCLE,
    brand: '',
    model: '',
    active: true,
    createdAt: todayIsoDate(),
    initialDistance: '',
    purchaseValue: '',
    purchaseDate: '',
    retiredDate: '',
    frameNumber: '',
    size: '',
    color: '',
    modelYear: '',
    groupset: '',
    specs: '',
    purchaseSource: '',
    notes: '',
  }
}

/** Converts the string-based form values into the clean {@link GearInput}. */
function buildInput(values: GearFormValues): GearInput {
  const isRacquet = values.gearType === GEAR_TYPE.RACQUET
  const distanceValue = toNumberOrNull(values.initialDistance)
  let initialKms: number | null = null
  if (!isRacquet && distanceValue !== null) {
    const km = props.units === 'imperial' ? milesToKm(distanceValue) : distanceValue
    initialKms = Math.round(km * 1000) / 1000
  }
  return {
    nickname: values.nickname.trim(),
    gearType: values.gearType,
    brand: cleanOptionalText(values.brand),
    model: cleanOptionalText(values.model),
    active: values.active,
    createdAt: values.createdAt || null,
    initialKms,
    purchaseValue: toNumberOrNull(values.purchaseValue),
    purchaseDate: values.purchaseDate || null,
    retiredDate: values.retiredDate || null,
    frameNumber: cleanOptionalText(values.frameNumber),
    size: cleanOptionalText(values.size),
    color: cleanOptionalText(values.color),
    modelYear: parseModelYear(values.modelYear),
    groupset: cleanOptionalText(values.groupset),
    specs: cleanOptionalText(values.specs),
    purchaseSource: cleanOptionalText(values.purchaseSource),
    notes: cleanOptionalText(values.notes),
  }
}

/**
 * Persists the gear, emitting the outcome to the parent and closing on success.
 * Backend failures (incl. the 409 duplicate-nickname guard the form can't check
 * synchronously) are mapped to a toast message rather than thrown, so the
 * dialog stays open for correction.
 *
 * @param values - The validated form values.
 */
async function submitForm(values: GearFormValues): Promise<void> {
  const input = buildInput(values)
  try {
    if (props.gear) {
      await updateMutation.mutateAsync({ id: props.gear.id, input })
      emit('success', t('gears.form.updateSuccess'))
    } else {
      await createMutation.mutateAsync(input)
      emit('success', t('gears.form.createSuccess'))
    }
    open.value = false
  } catch (error) {
    if (error instanceof HttpError && error.status === 409) {
      emit('error', t('gears.form.nicknameTaken'))
    } else {
      emit('error', t('gears.form.saveError'))
    }
  }
}

const { values, errors, isValid, isSubmitting, handleSubmit, handleBlur, validateField, reset } =
  useForm<GearFormValues>({
    initialValues: defaultValues(),
    validators: {
      nickname: compose(
        required<string>(t('gears.form.nicknameRequired')),
        maxLength(NICKNAME_MAX, t('gears.form.nicknameTooLong')),
      ),
      brand: maxLength(NICKNAME_MAX, t('gears.form.brandTooLong')),
      model: maxLength(NICKNAME_MAX, t('gears.form.modelTooLong')),
      createdAt: required<string>(t('gears.form.createdAtRequired')),
      retiredDate: (value: string) => {
        if (value && values.purchaseDate && value < values.purchaseDate) {
          return t('gears.form.retiredBeforePurchase')
        }
        return null
      },
      modelYear: (value: string | number) => {
        const trimmed = String(value ?? '').trim()
        if (!trimmed) {
          return null
        }
        const parsed = parseModelYear(trimmed)
        if (parsed === null || parsed < MODEL_YEAR_MIN || parsed > MODEL_YEAR_MAX) {
          return t('gears.form.modelYearInvalid')
        }
        return null
      },
      frameNumber: maxLength(FRAME_NUMBER_MAX, t('gears.form.frameNumberTooLong')),
      size: maxLength(SIZE_MAX, t('gears.form.sizeTooLong')),
      color: maxLength(COLOR_MAX, t('gears.form.colorTooLong')),
      groupset: maxLength(GROUPSET_MAX, t('gears.form.groupsetTooLong')),
      purchaseSource: maxLength(PURCHASE_SOURCE_MAX, t('gears.form.purchaseSourceTooLong')),
      specs: maxLength(SPECS_MAX, t('gears.form.specsTooLong')),
      notes: maxLength(NOTES_MAX, t('gears.form.notesTooLong')),
    },
    onSubmit: submitForm,
  })

watch(
  () => values.purchaseDate,
  () => {
    if (values.retiredDate) {
      validateField('retiredDate')
    }
  },
)

const isEditing = computed(() => props.gear !== null)
const dialogTitle = computed(() =>
  isEditing.value ? t('gears.form.editTitle') : t('gears.form.addTitle'),
)
// Racquets have no odometer, so the distance field is hidden for that type.
const showDistance = computed(() => values.gearType !== GEAR_TYPE.RACQUET)
const distanceUnitLabel = computed(() =>
  props.units === 'imperial' ? t('gears.unitMi') : t('gears.unitKm'),
)
const distanceLabel = computed(
  () => `${t('gears.form.initialDistance')} (${distanceUnitLabel.value})`,
)
const purchaseValueLabel = computed(
  () => `${t('gears.form.purchaseValue')} (${currencySymbol(props.currency)})`,
)

/** Seeds the form from the gear being edited, or pristine defaults for "add". */
function populate(): void {
  reset()
  values.createdAt = todayIsoDate()
  const gear = props.gear
  if (!gear) {
    return
  }
  values.nickname = gear.nickname
  values.gearType = gear.gearType
  values.brand = gear.brand ?? ''
  values.model = gear.model ?? ''
  values.active = gear.active
  values.createdAt = gear.createdAt ? gear.createdAt.slice(0, 10) : todayIsoDate()
  values.initialDistance = displayDistanceFromKm(gear.initialKms)
  values.purchaseValue = gear.purchaseValue !== null ? String(gear.purchaseValue) : ''
  values.purchaseDate = gear.purchaseDate ? gear.purchaseDate.slice(0, 10) : ''
  values.retiredDate = gear.retiredDate ? gear.retiredDate.slice(0, 10) : ''
  values.frameNumber = gear.frameNumber ?? ''
  values.size = gear.size ?? ''
  values.color = gear.color ?? ''
  values.modelYear = gear.modelYear !== null ? String(gear.modelYear) : ''
  values.groupset = gear.groupset ?? ''
  values.specs = gear.specs ?? ''
  values.purchaseSource = gear.purchaseSource ?? ''
  values.notes = gear.notes ?? ''
}

// Re-seed each time the dialog opens; the parent sets `gear` before opening.
watch(open, (isOpen) => {
  if (isOpen) {
    populate()
  }
})
</script>

<template>
  <FormDialog
    v-model:open="open"
    :title="dialogTitle"
    :description="t('gears.form.description')"
    :submit-label="isEditing ? t('gears.form.save') : t('gears.form.create')"
    :cancel-label="t('gears.form.cancel')"
    :close-label="t('gears.form.close')"
    :submitting="isSubmitting"
    :can-submit="isValid"
    content-class="sm:max-w-xl"
    @submit="handleSubmit"
  >
    <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
      <FormField
        class="sm:col-span-2"
        :label="t('gears.form.nickname')"
        :error="errors.nickname"
        :placeholder="t('gears.form.nickname')"
        required
      >
        <template #default="{ fieldId, describedBy, invalid, placeholder }">
          <Input
            :id="fieldId"
            v-model="values.nickname"
            :aria-describedby="describedBy"
            :aria-invalid="invalid"
            :placeholder="placeholder"
            name="nickname"
            maxlength="250"
            :disabled="isSubmitting"
            @blur="handleBlur('nickname')"
          />
        </template>
      </FormField>

      <FormField :label="t('gears.form.gearType')">
        <template #default="{ fieldId }">
          <Select :id="fieldId" v-model="values.gearType" :disabled="isSubmitting">
            <option v-for="type in GEAR_TYPE_VALUES" :key="type" :value="type">
              {{ t(presentGearType(type).labelKey) }}
            </option>
          </Select>
        </template>
      </FormField>

      <FormField :label="t('gears.form.createdAt')" :error="errors.createdAt" required>
        <template #default="{ fieldId, describedBy, invalid }">
          <input
            :id="fieldId"
            v-model="values.createdAt"
            :class="inputFieldClass"
            :aria-describedby="describedBy"
            :aria-invalid="invalid"
            type="date"
            :disabled="isSubmitting"
            @blur="handleBlur('createdAt')"
          />
        </template>
      </FormField>

      <FormField
        :label="t('gears.form.brand')"
        :error="errors.brand"
        :placeholder="t('gears.form.brand')"
      >
        <template #default="{ fieldId, describedBy, invalid, placeholder }">
          <Input
            :id="fieldId"
            v-model="values.brand"
            :aria-describedby="describedBy"
            :aria-invalid="invalid"
            :placeholder="placeholder"
            name="brand"
            maxlength="250"
            :disabled="isSubmitting"
            @blur="handleBlur('brand')"
          />
        </template>
      </FormField>

      <FormField
        :label="t('gears.form.model')"
        :error="errors.model"
        :placeholder="t('gears.form.model')"
      >
        <template #default="{ fieldId, describedBy, invalid, placeholder }">
          <Input
            :id="fieldId"
            v-model="values.model"
            :aria-describedby="describedBy"
            :aria-invalid="invalid"
            :placeholder="placeholder"
            name="model"
            maxlength="250"
            :disabled="isSubmitting"
            @blur="handleBlur('model')"
          />
        </template>
      </FormField>

      <FormField v-if="showDistance" :label="distanceLabel" :placeholder="distanceLabel">
        <template #default="{ fieldId, placeholder }">
          <input
            :id="fieldId"
            v-model="values.initialDistance"
            :class="inputFieldClass"
            :placeholder="placeholder"
            type="number"
            min="0"
            step="0.1"
            inputmode="decimal"
            :disabled="isSubmitting"
          />
        </template>
      </FormField>

      <FormField :label="purchaseValueLabel" :placeholder="purchaseValueLabel">
        <template #default="{ fieldId, placeholder }">
          <input
            :id="fieldId"
            v-model="values.purchaseValue"
            :class="inputFieldClass"
            :placeholder="placeholder"
            type="number"
            min="0"
            step="0.01"
            inputmode="decimal"
            :disabled="isSubmitting"
          />
        </template>
      </FormField>

      <Switch v-model="values.active" :disabled="isSubmitting" class="sm:col-span-2">
        {{ t('gears.form.active') }}
      </Switch>

      <h3
        class="sm:col-span-2 mt-2 border-t border-border pt-3 text-sm font-medium text-foreground"
      >
        {{ t('gears.profile.title') }}
      </h3>

      <FormField :label="t('gears.profile.purchaseDate')">
        <template #default="{ fieldId }">
          <input
            :id="fieldId"
            v-model="values.purchaseDate"
            :class="inputFieldClass"
            name="purchaseDate"
            type="date"
            :disabled="isSubmitting"
          />
        </template>
      </FormField>

      <FormField :label="t('gears.profile.retiredDate')" :error="errors.retiredDate">
        <template #default="{ fieldId, describedBy, invalid }">
          <input
            :id="fieldId"
            v-model="values.retiredDate"
            :class="inputFieldClass"
            :aria-describedby="describedBy"
            :aria-invalid="invalid"
            name="retiredDate"
            type="date"
            :disabled="isSubmitting"
            @blur="handleBlur('retiredDate')"
          />
        </template>
      </FormField>

      <FormField
        :label="t('gears.profile.modelYear')"
        :error="errors.modelYear"
        :placeholder="t('gears.form.modelYearPlaceholder')"
      >
        <template #default="{ fieldId, describedBy, invalid, placeholder }">
          <input
            :id="fieldId"
            v-model="values.modelYear"
            :class="inputFieldClass"
            :aria-describedby="describedBy"
            :aria-invalid="invalid"
            :placeholder="placeholder"
            name="modelYear"
            type="number"
            min="1900"
            max="2100"
            step="1"
            inputmode="numeric"
            :disabled="isSubmitting"
            @blur="handleBlur('modelYear')"
          />
        </template>
      </FormField>

      <FormField
        :label="t('gears.profile.size')"
        :error="errors.size"
        :placeholder="t('gears.form.sizePlaceholder')"
      >
        <template #default="{ fieldId, describedBy, invalid, placeholder }">
          <Input
            :id="fieldId"
            v-model="values.size"
            :aria-describedby="describedBy"
            :aria-invalid="invalid"
            :placeholder="placeholder"
            name="size"
            maxlength="50"
            :disabled="isSubmitting"
            @blur="handleBlur('size')"
          />
        </template>
      </FormField>

      <FormField
        :label="t('gears.profile.color')"
        :error="errors.color"
        :placeholder="t('gears.profile.color')"
      >
        <template #default="{ fieldId, describedBy, invalid, placeholder }">
          <Input
            :id="fieldId"
            v-model="values.color"
            :aria-describedby="describedBy"
            :aria-invalid="invalid"
            :placeholder="placeholder"
            name="color"
            maxlength="100"
            :disabled="isSubmitting"
            @blur="handleBlur('color')"
          />
        </template>
      </FormField>

      <FormField
        :label="t('gears.profile.frameNumber')"
        :error="errors.frameNumber"
        :placeholder="t('gears.profile.frameNumber')"
      >
        <template #default="{ fieldId, describedBy, invalid, placeholder }">
          <Input
            :id="fieldId"
            v-model="values.frameNumber"
            :aria-describedby="describedBy"
            :aria-invalid="invalid"
            :placeholder="placeholder"
            name="frameNumber"
            maxlength="100"
            :disabled="isSubmitting"
            @blur="handleBlur('frameNumber')"
          />
        </template>
      </FormField>

      <FormField
        :label="t('gears.profile.groupset')"
        :error="errors.groupset"
        :placeholder="t('gears.profile.groupset')"
      >
        <template #default="{ fieldId, describedBy, invalid, placeholder }">
          <Input
            :id="fieldId"
            v-model="values.groupset"
            :aria-describedby="describedBy"
            :aria-invalid="invalid"
            :placeholder="placeholder"
            name="groupset"
            maxlength="250"
            :disabled="isSubmitting"
            @blur="handleBlur('groupset')"
          />
        </template>
      </FormField>

      <FormField
        :label="t('gears.profile.purchaseSource')"
        :error="errors.purchaseSource"
        :placeholder="t('gears.profile.purchaseSource')"
      >
        <template #default="{ fieldId, describedBy, invalid, placeholder }">
          <Input
            :id="fieldId"
            v-model="values.purchaseSource"
            :aria-describedby="describedBy"
            :aria-invalid="invalid"
            :placeholder="placeholder"
            name="purchaseSource"
            maxlength="250"
            :disabled="isSubmitting"
            @blur="handleBlur('purchaseSource')"
          />
        </template>
      </FormField>

      <FormField
        class="sm:col-span-2"
        :label="t('gears.profile.specs')"
        :error="errors.specs"
        :placeholder="t('gears.form.specsPlaceholder')"
      >
        <template #default="{ fieldId, describedBy, invalid, placeholder }">
          <textarea
            :id="fieldId"
            v-model="values.specs"
            :class="inputFieldClass"
            :aria-describedby="describedBy"
            :aria-invalid="invalid"
            :placeholder="placeholder"
            name="specs"
            rows="3"
            maxlength="4000"
            :disabled="isSubmitting"
            @blur="handleBlur('specs')"
          />
        </template>
      </FormField>

      <FormField
        class="sm:col-span-2"
        :label="t('gears.profile.notes')"
        :error="errors.notes"
        :placeholder="t('gears.form.notesPlaceholder')"
      >
        <template #default="{ fieldId, describedBy, invalid, placeholder }">
          <textarea
            :id="fieldId"
            v-model="values.notes"
            :class="inputFieldClass"
            :aria-describedby="describedBy"
            :aria-invalid="invalid"
            :placeholder="placeholder"
            name="notes"
            rows="4"
            maxlength="8000"
            :disabled="isSubmitting"
            @blur="handleBlur('notes')"
          />
        </template>
      </FormField>
    </div>
  </FormDialog>
</template>
