import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import SavedRoutesDialog from '@/features/activities/components/SavedRoutesDialog.vue'
import {
  listRouteTrips,
  listSavedRoutes,
  sendRouteToTrip,
} from '@/features/activities/services/savedRoutes'
import i18n, { loadLocaleMessages, setI18nLocale } from '@/i18n'

vi.mock('@/features/activities/services/savedRoutes', () => ({
  listRouteTrips: vi.fn<typeof listRouteTrips>(),
  listSavedRoutes: vi.fn<typeof listSavedRoutes>(),
  sendRouteToTrip: vi.fn<typeof sendRouteToTrip>(),
}))

describe('saved routes trip picker', () => {
  it('requires the traveller to choose between trips, then sends the selected snapshot', async () => {
    await loadLocaleMessages('en')
    setI18nLocale('en')
    vi.mocked(listSavedRoutes).mockResolvedValue([
      { id: 9, name: 'Ridge ride', activity_type: 5, point_count: 30, source_activity_id: 4 },
    ])
    vi.mocked(listRouteTrips).mockResolvedValue([
      { id: 4, title: 'Islands' },
      { id: 7, title: 'Coast' },
    ])
    vi.mocked(sendRouteToTrip).mockResolvedValue({
      already_added: false,
      tour_id: 1,
      sent_points: 30,
    })
    const wrapper = mount(SavedRoutesDialog, {
      props: { open: false },
      global: {
        plugins: [i18n],
        stubs: {
          Dialog: { props: ['open'], template: '<div v-if="open"><slot /></div>' },
          DialogContent: { template: '<div><slot /></div>' },
          DialogHeader: { template: '<div><slot /></div>' },
          DialogFooter: { template: '<div><slot /></div>' },
          DialogTitle: { template: '<h2><slot /></h2>' },
        },
      },
    })
    await wrapper.setProps({ open: true })
    await flushPromises()
    expect(wrapper.text()).toContain('Ridge ride')
    expect(wrapper.text()).toContain('30 GPS points')
    expect(wrapper.get('button[type="submit"]').attributes('disabled')).toBeDefined()
    await wrapper.findAll('select')[1]!.setValue('7')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(sendRouteToTrip).toHaveBeenCalledWith(9, 7)
    expect(wrapper.emitted('update:open')).toEqual([[false]])
    wrapper.unmount()
  })
})
