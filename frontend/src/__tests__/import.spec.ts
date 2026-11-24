import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import i18n, { loadLocaleMessages } from '@/i18n'
import StravaImportGuideCard from '@/features/import/components/StravaImportGuideCard.vue'
import ImportSettingsView from '@/features/import/views/ImportSettingsView.vue'
import { apiFetch } from '@/services/http'
import {
  bulkImportFromArchive,
  bulkImportFromFolder,
  importStravaBikes,
  importStravaShoes,
} from '@/features/import/services/import'

vi.mock('@/services/http', () => ({
  apiFetch: vi.fn<typeof apiFetch>(),
}))

function csv(name = 'bikes.csv'): File {
  return new File(['Bike Name\n'], name, { type: 'text/csv' })
}

describe('import service', () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset()
    vi.mocked(apiFetch).mockResolvedValue(undefined)
  })

  it('bulkImportFromFolder POSTs the folder path for the chosen source and returns the one job', async () => {
    const job = { id: 'job-1' }
    vi.mocked(apiFetch).mockResolvedValueOnce(job)

    await expect(bulkImportFromFolder('strava')).resolves.toBe(job)
    expect(apiFetch).toHaveBeenCalledWith('/activities/bulk-import/folder?source=strava', {
      method: 'POST',
    })
  })

  it('bulkImportFromArchive uploads the archive as multipart with no request timeout', async () => {
    const job = { id: 'job-2' }
    vi.mocked(apiFetch).mockResolvedValueOnce(job)
    const archive = new File(['zip'], 'export.zip', { type: 'application/zip' })

    await expect(bulkImportFromArchive(archive, 'generic')).resolves.toBe(job)

    const [path, options] = vi.mocked(apiFetch).mock.calls[0]!
    expect(path).toBe('/activities/bulk-import?source=generic')
    expect(options).toMatchObject({ method: 'POST', timeoutMs: 0 })
    const body = (options as { body: FormData }).body
    expect(body).toBeInstanceOf(FormData)
    expect((body.get('file') as File).name).toBe('export.zip')
  })

  it('importStravaBikes uploads the CSV to the bikes import path (void)', async () => {
    await importStravaBikes(csv('bikes.csv'))

    const [path, options] = vi.mocked(apiFetch).mock.calls[0]!
    expect(path).toBe('/strava/import/bikes')
    expect(options).toMatchObject({ method: 'POST', responseType: 'void' })
    expect(((options as { body: FormData }).body.get('file') as File).name).toBe('bikes.csv')
  })

  it('importStravaShoes uploads the CSV to the shoes import path (void)', async () => {
    await importStravaShoes(csv('shoes.csv'))

    const [path, options] = vi.mocked(apiFetch).mock.calls[0]!
    expect(path).toBe('/strava/import/shoes')
    expect(options).toMatchObject({ method: 'POST', responseType: 'void' })
  })
})

describe('StravaImportGuideCard', () => {
  beforeEach(() => {
    i18n.global.locale.value = 'en'
  })

  it('renders download instructions, step order, exact-match warning, and notes in en', () => {
    const wrapper = mount(StravaImportGuideCard, {
      global: { plugins: [i18n] },
    })

    const text = wrapper.text()
    expect(text).toContain('Strava export import guide')
    expect(text).toContain('Request Your Archive')
    expect(text).toContain('bikes.csv')
    expect(text).toContain('shoes.csv')
    expect(text).toContain('activities.csv')
    expect(text).toContain('activities/')
    expect(text).toContain('media/')
    expect(text).toContain('Step 1')
    expect(text).toContain('Step 2')
    expect(text).toContain('exact nickname')
    expect(text).toContain('Simplified Chinese')
    expect(text).toContain('heart-rate zones')
  })

  it('collapses and re-expands when toggled', async () => {
    const wrapper = mount(StravaImportGuideCard, {
      global: { plugins: [i18n] },
    })

    const toggle = wrapper.find('button[aria-controls="strava-import-guide-body"]')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('#strava-import-guide-body').exists()).toBe(true)

    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('#strava-import-guide-body').exists()).toBe(false)

    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('#strava-import-guide-body').exists()).toBe(true)
  })

  it('renders full Strava import guide in zh-Hans', async () => {
    await loadLocaleMessages('zh-Hans')
    i18n.global.locale.value = 'zh-Hans'
    await flushPromises()

    const wrapper = mount(StravaImportGuideCard, {
      global: { plugins: [i18n] },
    })

    const text = wrapper.text()
    expect(text).toContain('Strava 导出导入指南')
    expect(text).toContain('Request Your Archive')
    expect(text).toContain('第 1 步')
    expect(text).toContain('第 2 步')
    expect(text).toContain('完全一致')
    expect(text).toContain('不会自动创建新装备')
    expect(text).toContain('简体中文')
    expect(text).toContain('心率区间')
  })

  it('is displayed on ImportSettingsView alongside StravaImportCard and BulkImportCard', () => {
    const wrapper = mount(ImportSettingsView, {
      global: {
        plugins: [i18n],
        stubs: {
          StravaImportCard: true,
          BulkImportCard: true,
        },
      },
    })

    expect(wrapper.findComponent(StravaImportGuideCard).exists()).toBe(true)
  })
})
