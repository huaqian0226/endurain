import { describe, expect, it } from 'vitest'
import { API_KEY_SCOPES } from '@/features/security/services/security'

describe('API key scopes', () => {
  it('matches the supported backend scope set', () => {
    expect([...API_KEY_SCOPES].sort()).toEqual(
      [
        'activities:read',
        'activities:write',
        'activities:upload',
        'workbench:read',
        'gears:read',
        'gears:write',
        'health:read',
        'health:write',
        'followers:read',
        'followers:write',
        'notifications:read',
        'notifications:write',
        'users:read',
      ].sort(),
    )
  })
})
