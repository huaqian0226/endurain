import { defineComponent, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import type { Gear, GearDetail, GearInput } from '@/features/gears/types'

import i18n, { loadLocaleMessages } from '@/i18n'
import GearProfileCard from '@/features/gears/components/GearProfileCard.vue'
import GearFormDialog from '@/features/gears/components/GearFormDialog.vue'

const createMutateAsync = vi.fn<(input: GearInput) => Promise<Gear>>()
const updateMutateAsync = vi.fn<(args: { id: number; input: GearInput }) => Promise<Gear>>()

vi.mock('@/features/gears/composables/useGears', () => ({
  useCreateGearMutation: () => ({ mutateAsync: createMutateAsync }),
  useUpdateGearMutation: () => ({ mutateAsync: updateMutateAsync }),
}))

const FormDialogStub = defineComponent({
  name: 'FormDialog',
  props: {
    open: { type: Boolean, default: false },
    title: { type: String, default: '' },
    canSubmit: { type: Boolean, default: true },
    submitting: { type: Boolean, default: false },
  },
  emits: ['update:open', 'submit'],
  template: `
    <form v-if="open" @submit.prevent="$emit('submit')">
      <slot />
      <button type="submit" :disabled="submitting || !canSubmit">submit</button>
    </form>
  `,
})

function makeGearDetail(overrides: Partial<GearDetail> = {}): GearDetail {
  return {
    id: 1,
    userId: 1,
    gearType: 1,
    nickname: 'Aero Synth',
    brand: 'BrandA',
    model: 'Aero Pro',
    active: true,
    createdAt: '2024-01-15T00:00:00Z',
    initialKms: 0,
    purchaseValue: 2000,
    stravaGearId: null,
    garminConnectGearId: null,
    purchaseDate: null,
    retiredDate: null,
    frameNumber: null,
    size: null,
    color: null,
    modelYear: null,
    groupset: null,
    specs: null,
    purchaseSource: null,
    notes: null,
    totalDistance: 100000,
    totalTime: 10800,
    totalComponentsCost: 200,
    ...overrides,
  }
}

describe('GearProfileCard', () => {
  beforeEach(() => {
    i18n.global.locale.value = 'en'
  })

  it('renders populated profile fields and hides empty ones', () => {
    const wrapper = mount(GearProfileCard, {
      props: {
        gear: makeGearDetail({
          purchaseDate: '2024-03-15',
          frameNumber: 'SYN-FRAME-001',
          size: '56',
          color: 'Matte Black',
          modelYear: 2013,
          groupset: 'Electronic 10-speed',
          specs: 'Front wheel: 82mm\nRear wheel: 101mm',
          purchaseSource: 'Local bike shop',
          notes: 'First line\nSecond line',
        }),
      },
      global: { plugins: [i18n] },
    })

    const text = wrapper.text()
    expect(text).toContain('Profile')
    expect(text).toContain('SYN-FRAME-001')
    expect(text).toContain('56')
    expect(text).toContain('Matte Black')
    expect(text).toContain('2013')
    expect(text).toContain('Electronic 10-speed')
    expect(text).toContain('Front wheel: 82mm')
    expect(text).toContain('Local bike shop')
    expect(text).toContain('First line')
    // Retired date was null so its label should not be rendered.
    expect(text).not.toContain('Retired date')
  })

  it('shows empty state when no profile fields are set on an active gear', () => {
    const wrapper = mount(GearProfileCard, {
      props: { gear: makeGearDetail() },
      global: { plugins: [i18n] },
    })

    expect(wrapper.find('dl').exists()).toBe(false)
    expect(wrapper.text()).toContain('No profile details recorded yet.')
  })

  it('shows a visible Retired badge with locale-formatted retired date', async () => {
    const gear = makeGearDetail({
      active: false,
      purchaseDate: '2020-04-01',
      retiredDate: '2026-05-15',
      notes: 'Retired after theft incident',
    })

    const enWrapper = mount(GearProfileCard, {
      props: { gear },
      global: { plugins: [i18n] },
    })
    expect(enWrapper.text()).toContain('Retired')
    expect(enWrapper.text()).toContain('2026')
    expect(enWrapper.text()).toContain('Retired after theft incident')

    await loadLocaleMessages('zh-Hans')
    i18n.global.locale.value = 'zh-Hans'
    const zhWrapper = mount(GearProfileCard, {
      props: { gear },
      global: { plugins: [i18n] },
    })
    expect(zhWrapper.text()).toContain('档案')
    expect(zhWrapper.text()).toContain('已停用')
    expect(zhWrapper.text()).toContain('2026')
  })

  it('renders notes as escaped plain text with preserved line breaks and never executes script tags', () => {
    const xssPayload = 'Line A\n<script>window.__xss=1</script>\n<img src=x onerror=alert(1)>'
    const wrapper = mount(GearProfileCard, {
      props: {
        gear: makeGearDetail({
          notes: xssPayload,
          specs: '<b>Not bold HTML</b>\nLine 2',
        }),
      },
      global: { plugins: [i18n] },
    })

    // No script or img or bold elements should be injected into the DOM.
    expect(wrapper.find('script').exists()).toBe(false)
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('b').exists()).toBe(false)

    // The literal strings are displayed safely as text.
    expect(wrapper.text()).toContain('<script>window.__xss=1</script>')
    expect(wrapper.text()).toContain('<b>Not bold HTML</b>')
    expect(wrapper.find('[data-testid="gear-profile-notes"]').classes()).toContain(
      'whitespace-pre-wrap',
    )
    expect(wrapper.find('[data-testid="gear-profile-specs"]').classes()).toContain(
      'whitespace-pre-wrap',
    )
  })
})

describe('GearFormDialog profile fields', () => {
  beforeEach(() => {
    i18n.global.locale.value = 'en'
    createMutateAsync.mockReset()
    updateMutateAsync.mockReset()
  })

  function mountForm(gear: Gear | null = null) {
    const open = ref(false)
    const wrapper = mount(
      defineComponent({
        components: { GearFormDialog },
        setup() {
          return { open, gear }
        },
        template: `
          <GearFormDialog
            v-model:open="open"
            :gear="gear"
            units="metric"
            currency="euro"
          />
        `,
      }),
      {
        global: {
          plugins: [i18n],
          stubs: { FormDialog: FormDialogStub },
        },
      },
    )
    return { wrapper, open }
  }

  it('submits all 10 profile fields when creating a gear', async () => {
    createMutateAsync.mockResolvedValueOnce(makeGearDetail())
    const { wrapper, open } = mountForm(null)
    open.value = true
    await flushPromises()

    await wrapper.find('input[name="nickname"]').setValue('Aero Bike')
    await wrapper.find('input[name="purchaseDate"]').setValue('2024-03-15')
    await wrapper.find('input[name="retiredDate"]').setValue('2026-05-15')
    await wrapper.find('input[name="frameNumber"]').setValue('  SYN-001  ')
    await wrapper.find('input[name="size"]').setValue('56')
    await wrapper.find('input[name="color"]').setValue('Matte Black')
    await wrapper.find('input[name="modelYear"]').setValue('2013')
    await wrapper.find('input[name="groupset"]').setValue('Electronic 10s')
    await wrapper.find('input[name="purchaseSource"]').setValue('Bike shop')
    await wrapper.find('textarea[name="specs"]').setValue('Wheels: 82/101\nTyres: 22mm')
    await wrapper.find('textarea[name="notes"]').setValue('   ')

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(createMutateAsync).toHaveBeenCalledTimes(1)
    const submitted = createMutateAsync.mock.calls[0]?.[0]
    expect(submitted).toMatchObject({
      nickname: 'Aero Bike',
      purchaseDate: '2024-03-15',
      retiredDate: '2026-05-15',
      frameNumber: 'SYN-001',
      size: '56',
      color: 'Matte Black',
      modelYear: 2013,
      groupset: 'Electronic 10s',
      purchaseSource: 'Bike shop',
      specs: 'Wheels: 82/101\nTyres: 22mm',
      notes: null,
    })
  })

  it('blocks submission when retiredDate is before purchaseDate', async () => {
    const { wrapper, open } = mountForm(null)
    open.value = true
    await flushPromises()

    await wrapper.find('input[name="nickname"]').setValue('Bad Dates Bike')
    await wrapper.find('input[name="purchaseDate"]').setValue('2025-06-10')
    await wrapper.find('input[name="retiredDate"]').setValue('2025-06-01')
    await wrapper.find('input[name="retiredDate"]').trigger('blur')
    await flushPromises()

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(createMutateAsync).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Retired date must be on or after the purchase date')
  })

  it('blocks submission when modelYear is outside 1900-2100', async () => {
    const { wrapper, open } = mountForm(null)
    open.value = true
    await flushPromises()

    await wrapper.find('input[name="nickname"]').setValue('Bad Year Bike')
    await wrapper.find('input[name="modelYear"]').setValue('1899')
    await wrapper.find('input[name="modelYear"]').trigger('blur')
    await flushPromises()

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(createMutateAsync).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Model year must be between 1900 and 2100')
  })

  it('populates existing profile fields when editing a gear', async () => {
    updateMutateAsync.mockResolvedValueOnce(makeGearDetail())
    const existing = makeGearDetail({
      id: 42,
      nickname: 'Old Roadie',
      active: false,
      purchaseDate: '2020-04-01',
      retiredDate: '2026-05-10',
      frameNumber: 'BN-777',
      size: '53',
      color: 'Celeste',
      modelYear: 2020,
      groupset: 'Sora 9s',
      purchaseSource: 'Retailer',
      specs: 'Alloy wheels',
      notes: 'Stolen in May 2026',
    })
    const { wrapper, open } = mountForm(existing)
    open.value = true
    await flushPromises()

    expect((wrapper.find('input[name="purchaseDate"]').element as HTMLInputElement).value).toBe(
      '2020-04-01',
    )
    expect((wrapper.find('input[name="retiredDate"]').element as HTMLInputElement).value).toBe(
      '2026-05-10',
    )
    expect((wrapper.find('input[name="frameNumber"]').element as HTMLInputElement).value).toBe(
      'BN-777',
    )
    expect((wrapper.find('input[name="modelYear"]').element as HTMLInputElement).value).toBe('2020')
    expect((wrapper.find('textarea[name="notes"]').element as HTMLTextAreaElement).value).toBe(
      'Stolen in May 2026',
    )
  })
})
