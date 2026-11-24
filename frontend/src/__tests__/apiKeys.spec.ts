import { defineComponent, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import type { ApiKey, ApiKeyCreatedDto, ApiKeyDto } from '@/features/security/types'

import i18n, { loadLocaleMessages } from '@/i18n'
import ApiKeyTempScopesDialog from '@/features/security/components/ApiKeyTempScopesDialog.vue'
import ApiKeysCard from '@/features/security/components/ApiKeysCard.vue'
import { apiFetch } from '@/services/http'
import {
  createApiKey,
  deleteApiKey,
  fetchApiKeys,
  grantApiKeyTempScopes,
  mapApiKey,
  revokeApiKey,
  revokeApiKeyTempScopes,
} from '@/features/security/services/security'

vi.mock('@/services/http', () => ({
  apiFetch: vi.fn<typeof apiFetch>(),
  HttpError: class HttpError extends Error {
    status: number
    constructor(status: number, message = 'error') {
      super(message)
      this.status = status
    }
  },
}))

const mockApiKeys = ref<ApiKey[]>([])
const grantMutate = vi.fn<(input: unknown, opts?: unknown) => void>()
const revokeTempMutate = vi.fn<(id: string, opts?: unknown) => void>()
const createMutate = vi.fn<(input: unknown, opts?: unknown) => void>()
const revokeMutate = vi.fn<(id: string, opts?: unknown) => void>()
const deleteMutate = vi.fn<(id: string, opts?: unknown) => void>()

vi.mock('@/features/security/composables/useSecurity', () => ({
  useApiKeysQuery: () => ({
    data: mockApiKeys,
    isPending: ref(false),
    isError: ref(false),
    refetch: vi.fn<() => void>(),
  }),
  useCreateApiKeyMutation: () => ({ mutate: createMutate, isPending: ref(false) }),
  useRevokeApiKeyMutation: () => ({ mutate: revokeMutate, isPending: ref(false) }),
  useDeleteApiKeyMutation: () => ({ mutate: deleteMutate, isPending: ref(false) }),
  useGrantApiKeyTempScopesMutation: () => ({ mutate: grantMutate, isPending: ref(false) }),
  useRevokeApiKeyTempScopesMutation: () => ({ mutate: revokeTempMutate, isPending: ref(false) }),
}))

const FormDialogStub = defineComponent({
  name: 'FormDialog',
  props: {
    open: { type: Boolean, default: false },
    title: { type: String, default: '' },
    description: { type: String, default: '' },
    submitLabel: { type: String, default: 'Submit' },
    canSubmit: { type: Boolean, default: true },
    submitting: { type: Boolean, default: false },
  },
  emits: ['update:open', 'submit'],
  template: `
    <form v-if="open" data-testid="temp-scopes-form" @submit.prevent="$emit('submit')">
      <h2>{{ title }}</h2>
      <p>{{ description }}</p>
      <slot />
      <button type="submit" :disabled="submitting || !canSubmit">{{ submitLabel }}</button>
    </form>
  `,
})

const apiKeyDto: ApiKeyDto = {
  id: 'key-1',
  user_id: 5,
  name: 'CI upload',
  key_prefix: 'endurain',
  scopes: '["activities:upload"]',
  temp_scopes: [],
  temp_scopes_expires_at: null,
  effective_scopes: ['activities:upload'],
  expires_at: '2026-12-31T00:00:00Z',
  last_used_at: '2026-06-01T00:00:00Z',
  created_at: '2026-01-01T00:00:00Z',
  is_active: true,
}

function makeApiKey(overrides: Partial<ApiKey> = {}): ApiKey {
  return {
    id: 'key-1',
    name: 'CI upload',
    keyPrefix: 'endurain',
    scopes: ['activities:read'],
    tempScopes: [],
    tempScopesExpiresAt: null,
    effectiveScopes: ['activities:read'],
    expiresAt: null,
    lastUsedAt: null,
    createdAt: '2026-01-01T00:00:00Z',
    isActive: true,
    ...overrides,
  }
}

describe('mapApiKey', () => {
  it('maps a full payload and parses the JSON scopes string', () => {
    expect(mapApiKey(apiKeyDto)).toEqual({
      id: 'key-1',
      name: 'CI upload',
      keyPrefix: 'endurain',
      scopes: ['activities:upload'],
      tempScopes: [],
      tempScopesExpiresAt: null,
      effectiveScopes: ['activities:upload'],
      expiresAt: '2026-12-31T00:00:00Z',
      lastUsedAt: '2026-06-01T00:00:00Z',
      createdAt: '2026-01-01T00:00:00Z',
      isActive: true,
    })
  })

  it('maps active temporary scopes and effective scopes', () => {
    const mapped = mapApiKey({
      ...apiKeyDto,
      temp_scopes: ['gears:write'],
      temp_scopes_expires_at: '2026-06-01T13:00:00Z',
      effective_scopes: ['activities:upload', 'gears:write'],
    })
    expect(mapped.tempScopes).toEqual(['gears:write'])
    expect(mapped.tempScopesExpiresAt).toBe('2026-06-01T13:00:00Z')
    expect(mapped.effectiveScopes).toEqual(['activities:upload', 'gears:write'])
  })

  it('defaults nullable fields and tolerates a malformed scopes string', () => {
    const mapped = mapApiKey({
      ...apiKeyDto,
      scopes: 'not-json',
      expires_at: null,
      last_used_at: null,
      is_active: false,
    })
    expect(mapped.scopes).toEqual([])
    expect(mapped.expiresAt).toBeNull()
    expect(mapped.lastUsedAt).toBeNull()
    expect(mapped.isActive).toBe(false)
  })
})

describe('api key service', () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset()
  })

  it('fetchApiKeys reads the path and maps the records', async () => {
    vi.mocked(apiFetch).mockResolvedValue([apiKeyDto])

    const keys = await fetchApiKeys()

    expect(apiFetch).toHaveBeenCalledWith(
      '/profile/api_keys',
      expect.objectContaining({ signal: undefined }),
    )
    expect(keys).toHaveLength(1)
    expect(keys[0]?.scopes).toEqual(['activities:upload'])
  })

  it('fetchApiKeys maps a null payload to an empty array', async () => {
    vi.mocked(apiFetch).mockResolvedValue(null)
    await expect(fetchApiKeys()).resolves.toEqual([])
  })

  it('createApiKey POSTs the body and returns the one-time raw key', async () => {
    const created: ApiKeyCreatedDto = { ...apiKeyDto, key: 'endurain_rawsecret' }
    vi.mocked(apiFetch).mockResolvedValue(created)

    const rawKey = await createApiKey({
      name: 'CI upload',
      scopes: ['activities:upload'],
      expiresAt: '2026-12-31',
      currentPassword: 'pw',
      mfaCode: '123456',
    })

    expect(rawKey).toBe('endurain_rawsecret')
    expect(apiFetch).toHaveBeenCalledWith('/profile/api_keys', {
      method: 'POST',
      body: JSON.stringify({
        name: 'CI upload',
        scopes: ['activities:upload'],
        expires_at: '2026-12-31',
        current_password: 'pw',
        mfa_code: '123456',
      }),
    })
  })

  it('revokeApiKey PATCHes the revoke path (void, id encoded)', async () => {
    vi.mocked(apiFetch).mockResolvedValue(undefined)

    await revokeApiKey('key 1')

    expect(apiFetch).toHaveBeenCalledWith('/profile/api_keys/key%201/revoke', {
      method: 'PATCH',
      responseType: 'void',
    })
  })

  it('deleteApiKey DELETEs the key path (void, id encoded)', async () => {
    vi.mocked(apiFetch).mockResolvedValue(undefined)

    await deleteApiKey('key 1')

    expect(apiFetch).toHaveBeenCalledWith('/profile/api_keys/key%201', {
      method: 'DELETE',
      responseType: 'void',
    })
  })

  it('grantApiKeyTempScopes PUTs scopes and duration_minutes and maps the response', async () => {
    const elevatedDto: ApiKeyDto = {
      ...apiKeyDto,
      temp_scopes: ['gears:write'],
      temp_scopes_expires_at: '2026-06-01T13:00:00Z',
      effective_scopes: ['activities:upload', 'gears:write'],
    }
    vi.mocked(apiFetch).mockResolvedValue(elevatedDto)

    const result = await grantApiKeyTempScopes({
      id: 'key 1',
      scopes: ['gears:write'],
      durationMinutes: 60,
    })

    expect(apiFetch).toHaveBeenCalledWith('/profile/api_keys/key%201/temp_scopes', {
      method: 'PUT',
      body: JSON.stringify({ scopes: ['gears:write'], duration_minutes: 60 }),
    })
    expect(result.tempScopes).toEqual(['gears:write'])
    expect(result.effectiveScopes).toEqual(['activities:upload', 'gears:write'])
  })

  it('revokeApiKeyTempScopes DELETEs the temp_scopes path and maps the response', async () => {
    vi.mocked(apiFetch).mockResolvedValue(apiKeyDto)

    const result = await revokeApiKeyTempScopes('key 1')

    expect(apiFetch).toHaveBeenCalledWith('/profile/api_keys/key%201/temp_scopes', {
      method: 'DELETE',
    })
    expect(result.tempScopes).toEqual([])
    expect(result.tempScopesExpiresAt).toBeNull()
  })
})

describe('ApiKeyTempScopesDialog', () => {
  beforeEach(() => {
    i18n.global.locale.value = 'en'
  })

  it('marks base scopes as included and submits selected temp scopes with preset duration', async () => {
    const wrapper = mount(ApiKeyTempScopesDialog, {
      props: {
        open: true,
        apiKey: makeApiKey({ scopes: ['activities:read'] }),
        pending: false,
      },
      global: {
        plugins: [i18n],
        stubs: { FormDialog: FormDialogStub },
      },
    })

    const baseCheckbox = wrapper.find('input[value="activities:read"]')
    expect((baseCheckbox.element as HTMLInputElement).checked).toBe(true)
    expect((baseCheckbox.element as HTMLInputElement).disabled).toBe(true)
    expect(wrapper.text()).toContain('Included')

    const submitButton = wrapper.find('button[type="submit"]')
    expect((submitButton.element as HTMLButtonElement).disabled).toBe(true)

    // Select gears:write and pick 6 h preset (360 minutes)
    const gearsWriteCheckbox = wrapper.find('input[value="gears:write"]')
    await gearsWriteCheckbox.setValue(true)

    const sixHoursBtn = wrapper.findAll('button[type="button"]').find((b) => b.text() === '6 h')
    expect(sixHoursBtn).toBeDefined()
    await sixHoursBtn!.trigger('click')

    expect((submitButton.element as HTMLButtonElement).disabled).toBe(false)
    await wrapper.find('form').trigger('submit')

    expect(wrapper.emitted('submit')).toEqual([
      [{ id: 'key-1', scopes: ['gears:write'], durationMinutes: 360 }],
    ])
  })

  it('supports custom duration in hours and rejects out-of-range durations', async () => {
    const wrapper = mount(ApiKeyTempScopesDialog, {
      props: {
        open: true,
        apiKey: makeApiKey({ scopes: ['activities:read'] }),
        pending: false,
      },
      global: {
        plugins: [i18n],
        stubs: { FormDialog: FormDialogStub },
      },
    })

    await wrapper.find('input[value="activities:write"]').setValue(true)

    const customBtn = wrapper.findAll('button[type="button"]').find((b) => b.text() === 'Custom')
    await customBtn!.trigger('click')

    const hoursBtn = wrapper.findAll('button[type="button"]').find((b) => b.text() === 'Hours')
    await hoursBtn!.trigger('click')

    const input = wrapper.find('#apikey-temp-custom-duration')
    // Out of range: 200 hours = 12000 minutes > 10080
    await input.setValue('200')
    expect((wrapper.find('button[type="submit"]').element as HTMLButtonElement).disabled).toBe(true)

    // Valid: 2 hours = 120 minutes
    await input.setValue('2')
    expect((wrapper.find('button[type="submit"]').element as HTMLButtonElement).disabled).toBe(
      false,
    )
    await wrapper.find('form').trigger('submit')

    expect(wrapper.emitted('submit')).toEqual([
      [{ id: 'key-1', scopes: ['activities:write'], durationMinutes: 120 }],
    ])
  })
})

describe('ApiKeysCard temporary access UI', () => {
  beforeEach(() => {
    i18n.global.locale.value = 'en'
    grantMutate.mockReset()
    revokeTempMutate.mockReset()
  })

  it('shows Temporary Access action, active temp badges, expiry, and triggers revoke', async () => {
    mockApiKeys.value = [
      makeApiKey({
        id: 'key-active',
        name: 'Uploader',
        scopes: ['activities:read'],
        tempScopes: ['gears:write', 'activities:write'],
        tempScopesExpiresAt: '2027-06-01T15:30:00Z',
        effectiveScopes: ['activities:read', 'gears:write', 'activities:write'],
      }),
      makeApiKey({
        id: 'key-revoked',
        name: 'Old Key',
        isActive: false,
      }),
    ]

    const wrapper = mount(ApiKeysCard, {
      props: { hasLocalPassword: true, mfaEnabled: false },
      global: {
        plugins: [i18n],
        stubs: {
          ApiKeyCreateDialog: true,
          ApiKeyRevealDialog: true,
          ConfirmDialog: true,
          FormDialog: FormDialogStub,
        },
      },
    })

    const text = wrapper.text()
    expect(text).toContain('Temporary Access')
    expect(text).toContain('Temporary')
    expect(text).toContain('gears:write')
    expect(text).toContain('activities:write')
    expect(text).toContain('Temporary access expires')

    // Only the active key gets a Temporary Access button (revoked key does not)
    const tempAccessButtons = wrapper
      .findAll('button')
      .filter((btn) => btn.text().includes('Temporary Access') && !btn.text().includes('Revoke'))
    expect(tempAccessButtons).toHaveLength(1)

    // Revoke Temporary Access button calls revoke mutation with the key id
    const revokeTempButton = wrapper
      .findAll('button')
      .find((btn) => btn.text().includes('Revoke Temporary Access'))
    expect(revokeTempButton).toBeDefined()
    await revokeTempButton!.trigger('click')
    expect(revokeTempMutate).toHaveBeenCalledWith('key-active', expect.any(Object))
  })

  it('renders Temporary Access and Revoke labels in zh-Hans', async () => {
    await loadLocaleMessages('zh-Hans')
    i18n.global.locale.value = 'zh-Hans'
    await flushPromises()

    mockApiKeys.value = [
      makeApiKey({
        id: 'key-zh',
        name: '同步脚本',
        scopes: ['activities:read'],
        tempScopes: ['gears:write'],
        tempScopesExpiresAt: '2027-06-01T15:30:00Z',
        effectiveScopes: ['activities:read', 'gears:write'],
      }),
    ]

    const wrapper = mount(ApiKeysCard, {
      props: { hasLocalPassword: true, mfaEnabled: false },
      global: {
        plugins: [i18n],
        stubs: {
          ApiKeyCreateDialog: true,
          ApiKeyRevealDialog: true,
          ConfirmDialog: true,
          FormDialog: FormDialogStub,
        },
      },
    })

    const text = wrapper.text()
    expect(text).toContain('临时提权')
    expect(text).toContain('撤销临时提权')
    expect(text).toContain('临时权限过期于')
  })
})
