import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createPinia, setActivePinia } from 'pinia'

import { apiFetch, HttpError } from '@/services/http'
import i18n, { loadLocaleMessages, setI18nLocale } from '@/i18n'
import { useAuthStore } from '@/features/auth/stores/auth'
import IntervalsSyncCard from '@/features/activities/components/IntervalsSyncCard.vue'

vi.mock('@/services/http', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/services/http')>()
  return { ...original, apiFetch: vi.fn<typeof apiFetch>() }
})

function mountCard(queryClient?: QueryClient) {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().isAuthenticated = true
  const client = queryClient ?? new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = mount(IntervalsSyncCard, {
    global: {
      plugins: [pinia, i18n, [VueQueryPlugin, { queryClient: client }]],
    },
  })
  return { wrapper, queryClient: client }
}

describe('IntervalsSyncCard', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    await loadLocaleMessages('zh-Hans')
    setI18nLocale('zh-Hans')
  })

  afterEach(() => {
    vi.useRealTimers()
    setI18nLocale('en')
  })

  it('hides the card when enabled is false', async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce({ enabled: false })
    const { wrapper } = mountCard()
    await flushPromises()
    expect(wrapper.text().trim()).toBe('')
    wrapper.unmount()
  })

  it('shows last sync time, result label, and auto-sync schedule when enabled', async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce({
      enabled: true,
      state: 'idle',
      last_started_at: '2026-11-23T21:59:00Z',
      last_finished_at: '2026-11-23T22:00:00Z',
      last_result: 'ok',
      counts: { done: 1, failed: 0, gave_up: 0, skipped: 0, pending: 0 },
      trigger: 'scheduled',
      last_requested_at: null,
      request_pending: false,
    })
    const { wrapper } = mountCard()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('intervals.icu 同步')
    expect(text).toContain('上次同步：')
    expect(text).toContain('成功')
    expect(text).toContain('自动同步：每天 22:00')
    expect(text).toContain('立即同步')
    wrapper.unmount()
  })

  it('shows empty record text when no sync has happened yet', async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce({
      enabled: true,
      state: 'unknown',
      last_started_at: null,
      last_finished_at: null,
      last_result: null,
      counts: null,
      trigger: null,
      last_requested_at: null,
      request_pending: false,
    })
    const { wrapper } = mountCard()
    await flushPromises()
    expect(wrapper.text()).toContain('还没有同步记录')
    wrapper.unmount()
  })

  it('sends POST on press, enters syncing state, polls every 5s, and refreshes activities when done', async () => {
    vi.useFakeTimers()
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')

    let pollCount = 0
    vi.mocked(apiFetch).mockImplementation(async (path, options) => {
      if (path === '/workbench/intervals-sync/requests' && options?.method === 'POST') {
        return { accepted: true, requested_at: '2026-11-23T22:05:00Z' }
      }
      if (path === '/workbench/intervals-sync') {
        pollCount += 1
        if (pollCount === 1) {
          return {
            enabled: true,
            state: 'idle',
            last_started_at: '2026-11-23T21:00:00Z',
            last_finished_at: '2026-11-23T21:01:00Z',
            last_result: 'ok',
            counts: { done: 0, failed: 0, gave_up: 0, skipped: 0, pending: 0 },
            trigger: 'scheduled',
            last_requested_at: null,
            request_pending: false,
          }
        }
        if (pollCount === 2) {
          return {
            enabled: true,
            state: 'running',
            last_started_at: '2026-11-23T22:05:01Z',
            last_finished_at: null,
            last_result: null,
            counts: null,
            trigger: 'manual',
            last_requested_at: '2026-11-23T22:05:00Z',
            request_pending: true,
          }
        }
        return {
          enabled: true,
          state: 'idle',
          last_started_at: '2026-11-23T22:05:01Z',
          last_finished_at: '2026-11-23T22:05:09Z',
          last_result: 'partial',
          counts: { done: 1, failed: 1, gave_up: 0, skipped: 0, pending: 0 },
          trigger: 'manual',
          last_requested_at: '2026-11-23T22:05:00Z',
          request_pending: false,
        }
      }
      throw new Error(`Unexpected path: ${path}`)
    })

    const { wrapper } = mountCard(queryClient)
    await flushPromises()

    const button = wrapper.find('button')
    expect(button.attributes('disabled')).toBeUndefined()
    await button.trigger('click')
    await flushPromises()

    const postCalls = vi
      .mocked(apiFetch)
      .mock.calls.filter(
        ([path, options]) =>
          path === '/workbench/intervals-sync/requests' && options?.method === 'POST',
      )
    expect(postCalls).toHaveLength(1)
    expect(wrapper.find('button').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('同步中…')
    expect(wrapper.text()).toContain('已发出同步请求，一般一两分钟内完成')

    await vi.advanceTimersByTimeAsync(5000)
    await flushPromises()
    expect(wrapper.find('button').attributes('disabled')).toBeDefined()

    await vi.advanceTimersByTimeAsync(5000)
    await flushPromises()
    expect(wrapper.find('button').attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).toContain('部分失败，下次会重试')
    expect(invalidateSpy).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: ['activities'] }),
    )
    wrapper.unmount()
  })

  it('disables the button while backend state is running', async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce({
      enabled: true,
      state: 'running',
      last_started_at: '2026-11-23T22:00:00Z',
      last_finished_at: null,
      last_result: null,
      counts: null,
      trigger: 'manual',
      last_requested_at: '2026-11-23T21:59:59Z',
      request_pending: true,
    })
    const { wrapper } = mountCard()
    await flushPromises()
    expect(wrapper.find('button').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('同步中…')
    wrapper.unmount()
  })

  it.each([
    ['running', '正在同步中'],
    ['recent', '刚刚已请求，请稍等'],
  ])('shows conflict message for 409 %s', async (detail, expected) => {
    vi.mocked(apiFetch).mockImplementation(async (path, options) => {
      if (path === '/workbench/intervals-sync/requests' && options?.method === 'POST') {
        throw new HttpError(409, 'Conflict', detail, 'urn:endurain:error:conflict')
      }
      return {
        enabled: true,
        state: 'idle',
        last_started_at: '2026-11-23T21:00:00Z',
        last_finished_at: '2026-11-23T21:01:00Z',
        last_result: 'ok',
        counts: { done: 0, failed: 0, gave_up: 0, skipped: 0, pending: 0 },
        trigger: 'scheduled',
        last_requested_at: null,
        request_pending: false,
      }
    })
    const { wrapper } = mountCard()
    await flushPromises()

    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain(expected)
    wrapper.unmount()
  })

  it('shows generic error message on non-409 POST error', async () => {
    vi.mocked(apiFetch).mockImplementation(async (path, options) => {
      if (path === '/workbench/intervals-sync/requests' && options?.method === 'POST') {
        throw new HttpError(
          503,
          'Service Unavailable',
          'unavailable',
          'urn:endurain:error:service-unavailable',
        )
      }
      return {
        enabled: true,
        state: 'idle',
        last_started_at: null,
        last_finished_at: null,
        last_result: null,
        counts: null,
        trigger: null,
        last_requested_at: null,
        request_pending: false,
      }
    })
    const { wrapper } = mountCard()
    await flushPromises()

    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('请求失败')
    wrapper.unmount()
  })

  it.each([
    ['missing_key', '钥匙串里缺少 key'],
    ['auth_rejected', 'key 被拒绝'],
    ['list_failed', '连不上 intervals.icu'],
    ['error', '出错了'],
  ] as const)('displays localized label for result %s', async (result, label) => {
    vi.mocked(apiFetch).mockResolvedValueOnce({
      enabled: true,
      state: 'idle',
      last_started_at: '2026-11-23T22:00:00Z',
      last_finished_at: '2026-11-23T22:00:10Z',
      last_result: result,
      counts: { done: 0, failed: 0, gave_up: 0, skipped: 0, pending: 0 },
      trigger: 'scheduled',
      last_requested_at: null,
      request_pending: false,
    })
    const { wrapper } = mountCard()
    await flushPromises()
    expect(wrapper.text()).toContain(label)
    wrapper.unmount()
  })
})
