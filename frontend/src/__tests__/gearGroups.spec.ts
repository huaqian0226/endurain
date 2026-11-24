import { computed, defineComponent, ref, toValue, type MaybeRefOrGetter } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import type { Gear, GearDetail, GearInput } from '@/features/gears/types'
import type { Schemas } from '@/types'

import i18n, { loadLocaleMessages } from '@/i18n'
import GearFormDialog from '@/features/gears/components/GearFormDialog.vue'
import GearProfileCard from '@/features/gears/components/GearProfileCard.vue'
import GearsView from '@/features/gears/views/GearsView.vue'
import {
  collectDistinctGroupNames,
  gearDistanceMeters,
  partitionGearsByGroup,
} from '@/features/gears/utils/gearGroups'

const mockUnits = ref<Schemas['Units']>('metric')
const mockAllGears = ref<Gear[]>([])
const mockSearchResults = ref<Gear[]>([])
const createMutateAsync = vi.fn<(input: GearInput) => Promise<Gear>>()
const updateMutateAsync = vi.fn<(args: { id: number; input: GearInput }) => Promise<Gear>>()
const deleteMutate = vi.fn<(id: number, options?: unknown) => void>()

vi.mock('@/features/auth/composables/useCurrentUser', () => ({
  useCurrentUser: () => ({
    data: computed(() => ({
      id: 1,
      units: mockUnits.value,
      currency: 'euro' as const,
    })),
  }),
}))

vi.mock('@/features/config/composables/useRecordsPerPage', () => ({
  useRecordsPerPage: () => ({ recordsPerPage: ref(25) }),
}))

vi.mock('@/composables/useToasts', () => ({
  useToasts: () => ({
    success: vi.fn<(message: string, duration?: number) => void>(),
    error: vi.fn<(message: string, duration?: number) => void>(),
  }),
}))

vi.mock('@/features/gears/composables/useGears', () => ({
  useGearsQuery: (
    _page: MaybeRefOrGetter<number>,
    _pageSize: MaybeRefOrGetter<number>,
    showInactive: MaybeRefOrGetter<boolean>,
  ) => {
    const records = computed(() =>
      toValue(showInactive) ? mockAllGears.value : mockAllGears.value.filter((gear) => gear.active),
    )
    return {
      data: computed(() => ({
        records: records.value,
        total: records.value.length,
      })),
      isPending: ref(false),
      isError: ref(false),
      refetch: vi.fn<() => void>(),
    }
  },
  useGearSearchQuery: (term: MaybeRefOrGetter<string>) => ({
    data: computed(() => {
      const q = toValue(term).trim().toLowerCase()
      if (!q) {
        return []
      }
      return mockSearchResults.value.length > 0
        ? mockSearchResults.value
        : mockAllGears.value.filter((gear) => gear.nickname.toLowerCase().includes(q))
    }),
    isPending: ref(false),
    isError: ref(false),
    refetch: vi.fn<() => void>(),
  }),
  useCreateGearMutation: () => ({ mutateAsync: createMutateAsync }),
  useUpdateGearMutation: () => ({ mutateAsync: updateMutateAsync }),
  useDeleteGearMutation: () => ({ mutate: deleteMutate, isPending: ref(false) }),
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

const RouterLinkStub = defineComponent({
  name: 'RouterLink',
  props: {
    to: { type: [String, Object], required: true },
  },
  template: '<a :data-to="JSON.stringify(to)"><slot /></a>',
})

const SwitchStub = defineComponent({
  name: 'SwitchStub',
  props: {
    modelValue: { type: Boolean, default: false },
  },
  emits: ['update:modelValue'],
  template: `
    <label>
      <input
        type="checkbox"
        :checked="modelValue"
        @change="$emit('update:modelValue', ($event.target).checked)"
      />
      <slot />
    </label>
  `,
})

const InlineWrapperStub = defineComponent({
  name: 'InlineWrapperStub',
  template: '<div><slot /></div>',
})

function makeGear(overrides: Partial<Gear> = {}): Gear {
  return {
    id: 1,
    userId: 1,
    gearType: 1,
    nickname: 'Synth Bike',
    groupName: null,
    brand: 'BrandA',
    model: 'ModelX',
    active: true,
    createdAt: '2025-01-01T00:00:00Z',
    initialKms: 0,
    totalDistance: 0,
    purchaseValue: null,
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
    stravaGearId: null,
    garminConnectGearId: null,
    ...overrides,
  }
}

function makeGearDetail(overrides: Partial<GearDetail> = {}): GearDetail {
  return {
    ...makeGear(),
    totalDistance: 50000,
    totalTime: 7200,
    totalComponentsCost: 0,
    ...overrides,
  }
}

describe('gearGroups utility', () => {
  it('resolves gear distance from totalDistance and falls back to initialKms', () => {
    expect(gearDistanceMeters(makeGear({ totalDistance: 12500, initialKms: 5 }))).toBe(12500)
    expect(gearDistanceMeters(makeGear({ totalDistance: null, initialKms: 12.5 }))).toBe(12500)
    expect(gearDistanceMeters(makeGear({ totalDistance: null, initialKms: null }))).toBe(0)
  })

  it('partitions gears into sorted groups with summed distances and flat ungrouped items', () => {
    const gears = [
      makeGear({ id: 1, nickname: 'Solo', groupName: null, totalDistance: 3000 }),
      makeGear({ id: 2, nickname: 'Road 1', groupName: '公路车', totalDistance: 10000 }),
      makeGear({ id: 3, nickname: 'Rental 1', groupName: '迪乐租', totalDistance: 2500 }),
      makeGear({ id: 4, nickname: 'Road 2', groupName: ' 公路车 ', totalDistance: 5500 }),
      makeGear({ id: 5, nickname: 'Blank Group', groupName: '   ', totalDistance: 1000 }),
    ]

    const result = partitionGearsByGroup(gears)
    expect(result.groups.map((g) => g.name)).toEqual(
      ['迪乐租', '公路车'].sort((a, b) => a.localeCompare(b)),
    )

    const road = result.groups.find((g) => g.name === '公路车')
    expect(road?.gears.map((g) => g.id)).toEqual([2, 4])
    expect(road?.totalDistanceMeters).toBe(15500)

    const rental = result.groups.find((g) => g.name === '迪乐租')
    expect(rental?.gears.map((g) => g.id)).toEqual([3])
    expect(rental?.totalDistanceMeters).toBe(2500)

    expect(result.ungrouped.map((g) => g.id)).toEqual([1, 5])
  })

  it('collects distinct sorted non-empty group names', () => {
    const gears = [
      makeGear({ id: 1, groupName: 'Road' }),
      makeGear({ id: 2, groupName: '  Gravel  ' }),
      makeGear({ id: 3, groupName: 'Road' }),
      makeGear({ id: 4, groupName: null }),
      makeGear({ id: 5, groupName: '   ' }),
    ]
    expect(collectDistinctGroupNames(gears)).toEqual(['Gravel', 'Road'])
  })
})

describe('GearsView grouping and filters', () => {
  beforeEach(() => {
    i18n.global.locale.value = 'en'
    mockUnits.value = 'metric'
    mockAllGears.value = []
    mockSearchResults.value = []
    createMutateAsync.mockReset()
    updateMutateAsync.mockReset()
    deleteMutate.mockReset()
  })

  function mountGearsView() {
    return mount(GearsView, {
      global: {
        plugins: [i18n],
        stubs: {
          RouterLink: RouterLinkStub,
          FormDialog: FormDialogStub,
          ConfirmDialog: true,
          Popover: InlineWrapperStub,
          PopoverTrigger: InlineWrapperStub,
          PopoverContent: InlineWrapperStub,
          Switch: SwitchStub,
        },
      },
    })
  }

  it('renders collapsible groups expanded by default with count and summed distance', async () => {
    mockAllGears.value = [
      makeGear({ id: 1, nickname: 'Road A', groupName: 'Road fleet', totalDistance: 12500 }),
      makeGear({ id: 2, nickname: 'Road B', groupName: 'Road fleet', totalDistance: 7500 }),
      makeGear({ id: 3, nickname: 'Road C', groupName: 'Road fleet', totalDistance: 5000 }),
      makeGear({ id: 4, nickname: 'Commuter', groupName: null, totalDistance: 4200 }),
    ]

    const wrapper = mountGearsView()
    await flushPromises()

    const sections = wrapper.findAll('[data-testid="gear-group-section"]')
    expect(sections).toHaveLength(1)

    const toggle = wrapper.find('[data-testid="gear-group-toggle"]')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('[data-testid="gear-group-name"]').text()).toBe('Road fleet')
    expect(wrapper.find('[data-testid="gear-group-count"]').text()).toBe('3 bikes')
    expect(wrapper.find('[data-testid="gear-group-distance"]').text()).toBe('25 km')

    // All three group members are visible inside the group with links and own distances.
    const groupItems = wrapper.find('[data-testid="gear-group-items"]')
    expect(groupItems.text()).toContain('Road A')
    expect(groupItems.text()).toContain('12.5 km')
    expect(groupItems.text()).toContain('Road B')
    expect(groupItems.text()).toContain('Road C')
    expect(groupItems.findAll('a')).toHaveLength(3)

    // Ungrouped gear stays in the flat list separated from groups (no ungrouped group section).
    const ungroupedList = wrapper.find('[data-testid="ungrouped-gears-list"]')
    expect(ungroupedList.exists()).toBe(true)
    expect(ungroupedList.classes()).toContain('border-t')
    expect(ungroupedList.text()).toContain('Commuter')
    expect(ungroupedList.text()).toContain('4.2 km')

    // Clicking the group header collapses its members; clicking again expands them.
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('[data-testid="gear-group-items"]').exists()).toBe(false)

    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('[data-testid="gear-group-items"]').exists()).toBe(true)
  })

  it('renders localized zh-Hans group counts and distances', async () => {
    await loadLocaleMessages('zh-Hans')
    i18n.global.locale.value = 'zh-Hans'
    mockAllGears.value = [
      makeGear({ id: 1, nickname: '车1', groupName: '迪乐租', totalDistance: 10000 }),
      makeGear({ id: 2, nickname: '车2', groupName: '迪乐租', totalDistance: 15500 }),
    ]

    const wrapper = mountGearsView()
    await flushPromises()

    expect(wrapper.find('[data-testid="gear-group-name"]').text()).toBe('迪乐租')
    expect(wrapper.find('[data-testid="gear-group-count"]').text()).toBe('2 辆')
    expect(wrapper.find('[data-testid="gear-group-distance"]').text()).toBe('25.5 公里')
  })

  it('keeps pure flat display when no gear has a group', async () => {
    mockAllGears.value = [
      makeGear({ id: 1, nickname: 'Plain A', groupName: null, totalDistance: 1000 }),
      makeGear({ id: 2, nickname: 'Plain B', groupName: null, totalDistance: 2000 }),
    ]

    const wrapper = mountGearsView()
    await flushPromises()

    expect(wrapper.find('[data-testid="gear-groups-container"]').exists()).toBe(false)
    const ungrouped = wrapper.find('[data-testid="ungrouped-gears-list"]')
    expect(ungrouped.exists()).toBe(true)
    expect(ungrouped.classes()).not.toContain('border-t')
    expect(ungrouped.text()).toContain('Plain A')
    expect(ungrouped.text()).toContain('Plain B')
  })

  it('hides empty groups and recalculates totals when inactive filter or search narrows members', async () => {
    vi.useFakeTimers()
    try {
      mockAllGears.value = [
        makeGear({
          id: 1,
          nickname: 'Active Road',
          groupName: 'Road fleet',
          active: true,
          totalDistance: 10000,
        }),
        makeGear({
          id: 2,
          nickname: 'Retired Road',
          groupName: 'Road fleet',
          active: false,
          totalDistance: 20000,
        }),
        makeGear({
          id: 3,
          nickname: 'Retired Rental',
          groupName: 'Old Rentals',
          active: false,
          totalDistance: 5000,
        }),
      ]

      const wrapper = mountGearsView()
      await flushPromises()

      // Inactive hidden by default: Old Rentals is empty -> hidden; Road fleet sums only active member.
      expect(wrapper.findAll('[data-testid="gear-group-section"]')).toHaveLength(1)
      expect(wrapper.find('[data-testid="gear-group-name"]').text()).toBe('Road fleet')
      expect(wrapper.find('[data-testid="gear-group-count"]').text()).toBe('1 bike')
      expect(wrapper.find('[data-testid="gear-group-distance"]').text()).toBe('10 km')

      // Enable "Show inactive": both groups appear with full member counts and sums.
      const checkbox = wrapper.find('input[type="checkbox"]')
      await checkbox.setValue(true)
      await flushPromises()

      const sections = wrapper.findAll('[data-testid="gear-group-section"]')
      expect(sections).toHaveLength(2)
      const roadSection = sections.find((s) => s.attributes('data-group-name') === 'Road fleet')
      expect(roadSection?.find('[data-testid="gear-group-count"]').text()).toBe('2 bikes')
      expect(roadSection?.find('[data-testid="gear-group-distance"]').text()).toBe('30 km')
      expect(roadSection?.text()).toContain('Inactive')

      // Search for "Rental": only Old Rentals remains visible.
      const searchInput = wrapper.find('input[type="search"]')
      await searchInput.setValue('Rental')
      vi.advanceTimersByTime(450)
      await flushPromises()

      const afterSearch = wrapper.findAll('[data-testid="gear-group-section"]')
      expect(afterSearch).toHaveLength(1)
      expect(afterSearch[0]?.find('[data-testid="gear-group-name"]').text()).toBe('Old Rentals')
      expect(afterSearch[0]?.find('[data-testid="gear-group-distance"]').text()).toBe('5 km')
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('GearFormDialog group field', () => {
  beforeEach(() => {
    i18n.global.locale.value = 'en'
    createMutateAsync.mockReset()
    updateMutateAsync.mockReset()
  })

  function mountForm(gear: Gear | null = null, existingGroups: string[] = []) {
    const open = ref(false)
    const wrapper = mount(
      defineComponent({
        components: { GearFormDialog },
        setup() {
          return { open, gear, existingGroups }
        },
        template: `
          <GearFormDialog
            v-model:open="open"
            :gear="gear"
            :existing-groups="existingGroups"
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

  it('populates datalist with distinct existing groups and trims input on create', async () => {
    createMutateAsync.mockResolvedValueOnce(makeGear({ groupName: '公路车' }))
    const { wrapper, open } = mountForm(null, ['公路车', '迪乐租'])
    open.value = true
    await flushPromises()

    const groupInput = wrapper.find('input[name="groupName"]')
    const datalistId = groupInput.attributes('list')
    expect(datalistId).toBeTruthy()
    const options = wrapper
      .findAll(`datalist#${datalistId} option`)
      .map((o) => o.attributes('value'))
    expect(options).toEqual(['公路车', '迪乐租'])

    await wrapper.find('input[name="nickname"]').setValue('Aero Bike')
    await groupInput.setValue('  公路车  ')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(createMutateAsync).toHaveBeenCalledTimes(1)
    expect(createMutateAsync.mock.calls[0]?.[0]).toMatchObject({
      nickname: 'Aero Bike',
      groupName: '公路车',
    })
  })

  it('sends groupName: null when clearing the field on edit', async () => {
    updateMutateAsync.mockResolvedValueOnce(makeGear({ id: 7, groupName: null }))
    const existing = makeGear({ id: 7, nickname: 'Rental #2', groupName: '迪乐租' })
    const { wrapper, open } = mountForm(existing, ['迪乐租'])
    open.value = true
    await flushPromises()

    const groupInput = wrapper.find('input[name="groupName"]')
    expect((groupInput.element as HTMLInputElement).value).toBe('迪乐租')

    await groupInput.setValue('   ')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(updateMutateAsync).toHaveBeenCalledTimes(1)
    expect(updateMutateAsync.mock.calls[0]?.[0]).toMatchObject({
      id: 7,
      input: expect.objectContaining({ groupName: null }),
    })
  })
})

describe('GearProfileCard group display', () => {
  beforeEach(() => {
    i18n.global.locale.value = 'en'
  })

  it('displays groupName as safe escaped plain text without injecting HTML', () => {
    const xssGroup = '<img src=x onerror=alert(1)>Road'
    const wrapper = mount(GearProfileCard, {
      props: {
        gear: makeGearDetail({ groupName: xssGroup }),
      },
      global: { plugins: [i18n] },
    })

    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('[data-testid="gear-profile-group"]').text()).toBe(xssGroup)
  })
})
