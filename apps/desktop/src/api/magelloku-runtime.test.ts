import { describe, expect, it, vi } from 'vitest'

import { MagellokuRuntime } from './magelloku-runtime'

const client = {
  setAccessToken: vi.fn(),
  startBrowserAuth: vi.fn().mockResolvedValue({ requestId: 'r1', state: 's1', authorizeUrl: 'https://magelloku.com/desktop/authorize', expiresAt: 'later' }),
  getBrowserAuthStatus: vi.fn().mockResolvedValueOnce({ status: 'PENDING' }).mockResolvedValueOnce({ status: 'APPROVED' }),
  exchangeApprovedBrowserGrant: vi.fn().mockResolvedValue({ accessToken: 'token-1', user: { id: 'u1', name: 'Farhan', email: 'f@example.com' } }),
  streamLlm: vi.fn()
}

describe('MagellokuRuntime', () => {
  it('opens browser auth, polls approval, exchanges grant, and persists token', async () => {
    const openExternal = vi.fn()
    const saveToken = vi.fn()
    const runtime = new MagellokuRuntime({ client: client as never, openExternal, saveToken, pollIntervalMs: 0, sleep: vi.fn() })

    await expect(runtime.signIn()).resolves.toMatchObject({ status: 'signed_in' })
    expect(openExternal).toHaveBeenCalledWith('https://magelloku.com/desktop/authorize')
    expect(client.exchangeApprovedBrowserGrant).toHaveBeenCalledWith('r1', 's1')
    expect(saveToken).toHaveBeenCalledWith('token-1')
  })

  it('defaults managed agent calls to QGIS balanced routing', async () => {
    const runtime = new MagellokuRuntime({ client: client as never })
    await runtime.stream({ idempotencyKey: 'k1', messages: [{ role: 'user', content: 'inspect layers' }] }, vi.fn())
    expect(client.streamLlm).toHaveBeenCalledWith(expect.objectContaining({ app: 'qgis', modelTier: 'balanced' }), expect.any(Function), undefined)
  })
})
