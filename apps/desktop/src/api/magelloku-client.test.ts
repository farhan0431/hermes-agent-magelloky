import { describe, expect, it, vi } from 'vitest'

import { MagellokuClient } from './magelloku-client'

describe('MagellokuClient', () => {
  it('uses the production API and sends the desktop app contract', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ data: { requestId: 'req-1', state: 'state-1', authorizeUrl: 'https://magelloku.com/desktop/authorize' } }), {
        status: 200,
        headers: { 'content-type': 'application/json' }
      })
    )
    const client = new MagellokuClient({ fetchImpl })

    const result = await client.startBrowserAuth()

    expect(result.requestId).toBe('req-1')
    expect(fetchImpl).toHaveBeenCalledWith(
      'https://api.magelloku.com/api/v1/desktop/auth/requests',
      expect.objectContaining({ method: 'POST' })
    )
  })

  it('attaches the desktop bearer token to AI requests', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ data: { output: 'ok' } }), {
        status: 200,
        headers: { 'content-type': 'application/json' }
      })
    )
    const client = new MagellokuClient({ fetchImpl, accessToken: 'desktop-token' })

    await client.respondLlm({ app: 'qgis', tier: 'balanced', messages: [{ role: 'user', content: 'hello' }] })

    const [, request] = fetchImpl.mock.calls[0]
    expect(request?.headers).toBeInstanceOf(Headers)
    expect((request?.headers as Headers).get('authorization')).toBe('Bearer desktop-token')
    expect(fetchImpl).toHaveBeenCalledWith(
      'https://api.magelloku.com/api/v1/desktop/llm/respond',
      expect.objectContaining({ method: 'POST' })
    )
  })
})

const _compileOnly = MagellokuClient
void _compileOnly

