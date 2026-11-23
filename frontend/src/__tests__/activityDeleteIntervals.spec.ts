import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createPinia, setActivePinia } from 'pinia'

import { apiFetch, HttpError } from '@/services/http'
import i18n, { loadLocaleMessages, setI18nLocale } from '@/i18n'
import { useAuthStore } from '@/features/auth/stores/auth'
import { useToasts } from '@/composables/useToasts'
import { mapActivity } from '@/features/activities/services/activities'
import ActivityActionsMenu from '@/features/activities/components/ActivityActionsMenu.vue'

const pushMock = vi.fn<() => Promise<void>>().mockResolvedValue(undefined)

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: pushMock }),
}))

vi.mock('@/services/http', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/services/http')>()
  return { ...original, apiFetch: vi.fn<typeof apiFetch>() }
})

const passthrough = { template: '<div><slot /></div>' }
const dropdownItemStub = {
  template: '<button type="button" @click="$emit(\'select\')"><slot /></button>',
  emits: ['select'],
}
const dialogStub = {
  props: ['open'],
  emits: ['update:open'],
  template: '<div v-if="open" data-testid="dialog"><slot /></div>',
}

const sampleActivity = mapActivity({
  id: 7,
  user_id: 1,
  name: 'Morning Ride',
  activity_type: 1,
  distance: 25000,
  is_hidden: false,
  equipment_confirmed: false,
  version: 1,
})

function mountActionsMenu() {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().isAuthenticated = true
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = mount(ActivityActionsMenu, {
    props: { activity: sampleActivity },
    global: {
      plugins: [pinia, i18n, [VueQueryPlugin, { queryClient }]],
      stubs: {
        ActivityEditDialog: true,
        DropdownMenu: passthrough,
        DropdownMenuTrigger: passthrough,
        DropdownMenuContent: passthrough,
        DropdownMenuSeparator: true,
        DropdownMenuItem: dropdownItemStub,
        Dialog: dialogStub,
        DialogContent: passthrough,
        DialogHeader: passthrough,
        DialogTitle: passthrough,
        DialogDescription: passthrough,
        DialogFooter: passthrough,
      },
    },
  })
  return { wrapper, queryClient }
}

function clearToasts() {
  const { toasts, dismiss } = useToasts()
  const ids = toasts.value.map((toast) => toast.id)
  for (const id of ids) {
    dismiss(id)
  }
}

async function openDeleteDialog(wrapper: ReturnType<typeof mountActionsMenu>['wrapper']) {
  const deleteTrigger = wrapper.findAll('button').find((btn) => btn.text().includes('删除活动'))
  expect(deleteTrigger).toBeTruthy()
  await deleteTrigger!.trigger('click')
  await flushPromises()
}

async function clickConfirmDelete(wrapper: ReturnType<typeof mountActionsMenu>['wrapper']) {
  const dialog = wrapper.find('[data-testid="dialog"]')
  expect(dialog.exists()).toBe(true)
  const confirmButton = dialog.findAll('button').find((btn) => btn.text().includes('删除活动'))
  expect(confirmButton).toBeTruthy()
  await confirmButton!.trigger('click')
  await flushPromises()
}

describe('ActivityActionsMenu intervals.icu delete option', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    clearToasts()
    await loadLocaleMessages('zh-Hans')
    setI18nLocale('zh-Hans')
  })

  afterEach(() => {
    clearToasts()
    setI18nLocale('en')
  })

  it('hides checkbox when activity has no intervals_id and only calls native DELETE', async () => {
    vi.mocked(apiFetch).mockImplementation(async (path, options) => {
      if (path === '/workbench/intervals-sync/activities/7') {
        return { intervals_id: null }
      }
      if (path === '/activities/7' && options?.method === 'DELETE') {
        return undefined
      }
      throw new Error(`Unexpected request: ${options?.method ?? 'GET'} ${path}`)
    })

    const { wrapper } = mountActionsMenu()
    await openDeleteDialog(wrapper)

    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)

    await clickConfirmDelete(wrapper)

    expect(vi.mocked(apiFetch)).toHaveBeenCalledWith('/activities/7', { method: 'DELETE' })
    expect(
      vi
        .mocked(apiFetch)
        .mock.calls.filter(([path]) => path === '/workbench/intervals-sync/delete-requests'),
    ).toHaveLength(0)
    expect(useToasts().toasts.value.map((t) => t.message)).toContain('活动已删除')
    expect(pushMock).toHaveBeenCalledWith({ name: 'home' })
    wrapper.unmount()
  })

  it('hides checkbox when lookup query fails and still deletes natively', async () => {
    vi.mocked(apiFetch).mockImplementation(async (path, options) => {
      if (path === '/workbench/intervals-sync/activities/7') {
        throw new HttpError(500, 'Internal Server Error')
      }
      if (path === '/activities/7' && options?.method === 'DELETE') {
        return undefined
      }
      throw new Error(`Unexpected request: ${options?.method ?? 'GET'} ${path}`)
    })

    const { wrapper } = mountActionsMenu()
    await openDeleteDialog(wrapper)

    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)

    await clickConfirmDelete(wrapper)
    expect(vi.mocked(apiFetch)).toHaveBeenCalledWith('/activities/7', { method: 'DELETE' })
    expect(
      vi
        .mocked(apiFetch)
        .mock.calls.filter(([path]) => path === '/workbench/intervals-sync/delete-requests'),
    ).toHaveLength(0)
    wrapper.unmount()
  })

  it('shows unchecked checkbox when intervals_id exists, resets on reopen, and skips POST when unchecked', async () => {
    vi.mocked(apiFetch).mockImplementation(async (path, options) => {
      if (path === '/workbench/intervals-sync/activities/7') {
        return { intervals_id: 'i42' }
      }
      if (path === '/activities/7' && options?.method === 'DELETE') {
        return undefined
      }
      throw new Error(`Unexpected request: ${options?.method ?? 'GET'} ${path}`)
    })

    const { wrapper } = mountActionsMenu()
    await openDeleteDialog(wrapper)

    const dialog = wrapper.find('[data-testid="dialog"]')
    expect(dialog.text()).toContain('同时删除 intervals.icu 上的这条（删除后无法恢复）')
    expect(dialog.text()).toContain(
      '只删 intervals.icu 上的副本；iGPSPORT 和 Strava 上的不受影响。',
    )

    const checkbox = dialog.find('input[type="checkbox"]')
    expect(checkbox.exists()).toBe(true)
    expect((checkbox.element as HTMLInputElement).checked).toBe(false)

    // Check, cancel, reopen -> must reset to unchecked
    await checkbox.setValue(true)
    expect((checkbox.element as HTMLInputElement).checked).toBe(true)
    const cancelBtn = dialog.findAll('button').find((btn) => btn.text().includes('取消'))
    await cancelBtn!.trigger('click')
    await flushPromises()

    await openDeleteDialog(wrapper)
    const reopenedCheckbox = wrapper.find('[data-testid="dialog"] input[type="checkbox"]')
    expect((reopenedCheckbox.element as HTMLInputElement).checked).toBe(false)

    await clickConfirmDelete(wrapper)
    expect(vi.mocked(apiFetch)).toHaveBeenCalledWith('/activities/7', { method: 'DELETE' })
    expect(
      vi
        .mocked(apiFetch)
        .mock.calls.filter(([path]) => path === '/workbench/intervals-sync/delete-requests'),
    ).toHaveLength(0)
    wrapper.unmount()
  })

  it('calls native DELETE first then POST delete-requests when checked and shows combined toast', async () => {
    const callOrder: string[] = []
    let deleteRequestBody = ''
    vi.mocked(apiFetch).mockImplementation(async (path, options) => {
      if (path === '/workbench/intervals-sync/activities/7') {
        return { intervals_id: 'i42' }
      }
      if (path === '/activities/7' && options?.method === 'DELETE') {
        callOrder.push('DELETE /activities/7')
        return undefined
      }
      if (path === '/workbench/intervals-sync/delete-requests' && options?.method === 'POST') {
        callOrder.push('POST /workbench/intervals-sync/delete-requests')
        deleteRequestBody = String(options.body ?? '')
        return { accepted: true, request_id: 'a'.repeat(32), intervals_id: 'i42' }
      }
      throw new Error(`Unexpected request: ${options?.method ?? 'GET'} ${path}`)
    })

    const { wrapper } = mountActionsMenu()
    await openDeleteDialog(wrapper)

    await wrapper.find('[data-testid="dialog"] input[type="checkbox"]').setValue(true)
    await clickConfirmDelete(wrapper)

    expect(callOrder).toEqual([
      'DELETE /activities/7',
      'POST /workbench/intervals-sync/delete-requests',
    ])
    expect(JSON.parse(deleteRequestBody)).toEqual({ activity_id: 7 })
    const toastMessages = useToasts()
      .toasts.value.map((t) => t.message)
      .join(' ')
    expect(toastMessages).toContain('活动已删除')
    expect(toastMessages).toContain('已请求删除 intervals.icu 上的这条，会在 Mac 上执行')
    expect(pushMock).toHaveBeenCalledWith({ name: 'home' })
    wrapper.unmount()
  })

  it('does not call POST delete-requests when native DELETE fails', async () => {
    vi.mocked(apiFetch).mockImplementation(async (path, options) => {
      if (path === '/workbench/intervals-sync/activities/7') {
        return { intervals_id: 'i42' }
      }
      if (path === '/activities/7' && options?.method === 'DELETE') {
        throw new HttpError(500, 'Internal Server Error')
      }
      throw new Error(`Unexpected request: ${options?.method ?? 'GET'} ${path}`)
    })

    const { wrapper } = mountActionsMenu()
    await openDeleteDialog(wrapper)
    await wrapper.find('[data-testid="dialog"] input[type="checkbox"]').setValue(true)
    await clickConfirmDelete(wrapper)

    expect(
      vi
        .mocked(apiFetch)
        .mock.calls.filter(([path]) => path === '/workbench/intervals-sync/delete-requests'),
    ).toHaveLength(0)
    expect(useToasts().toasts.value.map((t) => t.message)).toContain('无法删除活动')
    expect(pushMock).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('shows partial-failure toast and still navigates home when POST delete-requests fails', async () => {
    vi.mocked(apiFetch).mockImplementation(async (path, options) => {
      if (path === '/workbench/intervals-sync/activities/7') {
        return { intervals_id: 'i42' }
      }
      if (path === '/activities/7' && options?.method === 'DELETE') {
        return undefined
      }
      if (path === '/workbench/intervals-sync/delete-requests' && options?.method === 'POST') {
        throw new HttpError(503, 'Service Unavailable')
      }
      throw new Error(`Unexpected request: ${options?.method ?? 'GET'} ${path}`)
    })

    const { wrapper } = mountActionsMenu()
    await openDeleteDialog(wrapper)
    await wrapper.find('[data-testid="dialog"] input[type="checkbox"]').setValue(true)
    await clickConfirmDelete(wrapper)

    expect(useToasts().toasts.value.map((t) => t.message)).toContain(
      'Endurain 已删除，但 intervals.icu 删除请求没有发出',
    )
    expect(pushMock).toHaveBeenCalledWith({ name: 'home' })
    wrapper.unmount()
  })
})
