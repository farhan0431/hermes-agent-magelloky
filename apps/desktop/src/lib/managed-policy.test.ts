import { describe, expect, it } from 'vitest'

import { isManagedRouteAllowed, isManagedMutationAllowed, MANAGED_DISABLED_ROUTE_PATHS } from '../../electron/managed-policy'

describe('Magelloku managed policy', () => {
  it('rejects disabled route families including query and hash bypasses', () => {
    for (const path of MANAGED_DISABLED_ROUTE_PATHS) {
      expect(isManagedRouteAllowed(path)).toBe(false)
      expect(isManagedRouteAllowed(`${path}?tab=anything#x`)).toBe(false)
    }
    expect(isManagedRouteAllowed('/')).toBe(true)
    expect(isManagedRouteAllowed('/artifacts')).toBe(true)
  })

  it('rejects configuration and plugin mutations at the boundary', () => {
    expect(isManagedMutationAllowed('hermes:plugin:installDesktop')).toBe(false)
    expect(isManagedMutationAllowed('hermes:plugin:removeDesktop')).toBe(false)
    expect(isManagedMutationAllowed('hermes:fs:reconcileDesktopPlugins')).toBe(false)
    expect(isManagedMutationAllowed('hermes:fs:readDir')).toBe(true)
  })
})
