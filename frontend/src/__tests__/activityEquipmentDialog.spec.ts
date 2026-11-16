import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createPinia, setActivePinia } from 'pinia'

import { apiFetch } from '@/services/http'
import i18n from '@/i18n'
import { useAuthStore } from '@/features/auth/stores/auth'
import { mapActivity } from '@/features/activities/services/activities'
import ActivityEditDialog from '@/features/activities/components/ActivityEditDialog.vue'

vi.mock('@/services/http', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/services/http')>()
  return { ...original, apiFetch: vi.fn<typeof apiFetch>() }
})

const helmet = '00000000-0000-4000-8000-000000000101'
const lamp = '00000000-0000-4000-8000-000000000102'
const dto = {
  id: 2,
  user_id: 1,
  name: 'Ride',
  activity_type: 1,
  distance: 12000,
  is_hidden: false,
  equipment_confirmed: false,
  gear_id: 1,
  version: 3,
}
const passthrough = { template: '<div><slot /></div>' }

function mountEditor() {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().isAuthenticated = true
  return mount(ActivityEditDialog, {
    props: { open: true, activity: mapActivity(dto) },
    global: {
      plugins: [
        pinia,
        i18n,
        [
          VueQueryPlugin,
          { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
        ],
      ],
      stubs: {
        Dialog: passthrough,
        DialogContent: passthrough,
        DialogHeader: passthrough,
        DialogTitle: passthrough,
        DialogDescription: passthrough,
        DialogFooter: passthrough,
      },
    },
  })
}

describe('Native activity equipment editor', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('saves the primary vehicle and two actual equipment selections in one conditional PATCH', async () => {
    vi.mocked(apiFetch).mockImplementation(async (path) => {
      if (String(path).includes('equipment-candidates'))
        return {
          schema_version: 1,
          revision: 'catalogue-1',
          observed_at: '2026-11-16T00:00:00Z',
          items: [
            { asset_id: helmet, label: 'Helmet', status: 'active' },
            { asset_id: lamp, label: 'Lamp', status: 'active' },
          ],
        }
      if (String(path).includes('/gears/type/'))
        return [
          { id: 1, user_id: 1, nickname: 'Venge', gear_type: 1 },
          { id: 2, user_id: 1, nickname: 'Second', gear_type: 1 },
        ]
      return dto
    })
    const wrapper = mountEditor()
    await flushPromises()
    const labelSelect = (label: string) => {
      const node = wrapper.findAll('label').find((item) => item.text() === label)
      expect(node).toBeTruthy()
      return wrapper.find(`select[id="${node?.attributes('for')}"]`)
    }
    await labelSelect('Primary vehicle or gear').setValue('2')
    await labelSelect('Helmet').setValue('used')
    await labelSelect('Lamp').setValue('carried')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    const writes = vi
      .mocked(apiFetch)
      .mock.calls.filter(([, options]) => options?.method === 'PATCH')
    expect(writes).toHaveLength(1)
    expect(writes[0]?.[0]).toBe('/activities/2')
    expect(writes[0]?.[1]?.headers).toEqual({ 'If-Match': '"3"' })
    expect(JSON.parse(String(writes[0]?.[1]?.body))).toMatchObject({
      gear_id: 2,
      equipment_selection: {
        confirmed: true,
        items: [
          { asset_id: helmet, use_mode: 'used' },
          { asset_id: lamp, use_mode: 'carried' },
        ],
      },
    })
    wrapper.unmount()
  })

  it('uses the edit baseline even if background refresh changes the activity version', async () => {
    vi.mocked(apiFetch).mockImplementation(async (path) => {
      if (String(path).includes('equipment-candidates')) return { items: [] }
      if (String(path).includes('/gears/type/')) return []
      return dto
    })
    const wrapper = mountEditor()
    await flushPromises()
    await wrapper.setProps({
      activity: mapActivity({ ...dto, version: 8, name: 'New server edit' }),
    })
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    const write = vi.mocked(apiFetch).mock.calls.find(([, options]) => options?.method === 'PATCH')
    expect(write?.[1]?.headers).toEqual({ 'If-Match': '"3"' })
    expect(JSON.parse(String(write?.[1]?.body)).name).toBe('Ride')
    wrapper.unmount()
  })

  it('keeps equipment unchanged when the authority is unavailable', async () => {
    vi.mocked(apiFetch).mockImplementation(async (path) => {
      if (String(path).includes('equipment-candidates')) throw new Error('offline')
      if (String(path).includes('/gears/type/')) return []
      return dto
    })
    const wrapper = mountEditor()
    await flushPromises()
    expect(wrapper.text()).toContain('Existing selections are preserved')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    const write = vi.mocked(apiFetch).mock.calls.find(([, options]) => options?.method === 'PATCH')
    expect(JSON.parse(String(write?.[1]?.body))).not.toHaveProperty('equipment_selection')
    wrapper.unmount()
  })
})
