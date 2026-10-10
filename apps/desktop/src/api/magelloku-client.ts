export type MagellokuApp = 'qgis' | 'surpac'
export type MagellokuTier = 'economy' | 'balanced' | 'premium'
export type MagellokuMessage = { role: 'system' | 'user' | 'assistant' | 'tool'; content?: unknown }

export type MagellokuClientOptions = {
  apiBaseUrl?: string
  accessToken?: string | null
  fetchImpl?: typeof fetch
}

type Envelope<T> = { data: T }

export class MagellokuClient {
  private readonly baseUrl: string
  private readonly fetchImpl: typeof fetch
  private accessToken: string | null

  constructor(options: MagellokuClientOptions = {}) {
    this.baseUrl = (options.apiBaseUrl ?? 'https://api.magelloku.com/api/v1').replace(/\/$/, '')
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis)
    this.accessToken = options.accessToken ?? null
  }

  setAccessToken(token: string | null) {
    this.accessToken = token
  }

  private async request<T>(path: string, init: RequestInit = {}, authenticated = true): Promise<T> {
    const headers = new Headers(init.headers)
    headers.set('content-type', 'application/json')
    if (authenticated && this.accessToken) headers.set('authorization', `Bearer ${this.accessToken}`)
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, { ...init, headers })
    const body = (await response.json()) as Envelope<T> | { error?: { message?: string } }
    if (!response.ok) throw new Error(('error' in body && body.error?.message) || `Magelloku API request failed (${response.status})`)
    return 'data' in body ? body.data : (body as T)
  }

  startBrowserAuth(input: { name?: string; platform?: string; app?: MagellokuApp } = {}) {
    return this.request<{ requestId: string; state: string; authorizeUrl: string; expiresAt: string }>('/desktop/auth/requests', { method: 'POST', body: JSON.stringify(input) }, false)
  }

  getBrowserAuthStatus(requestId: string, state: string) {
    return this.request<{ status: 'PENDING' | 'APPROVED' | 'CONSUMED' | 'EXPIRED' }>(`/desktop/auth/requests/${encodeURIComponent(requestId)}?state=${encodeURIComponent(state)}`, {}, false)
  }

  exchangeApprovedBrowserGrant(requestId: string, state: string) {
    return this.request<{ accessToken: string; expiresAt: string; user?: { id: string; name: string; email: string } }>(`/desktop/auth/requests/${encodeURIComponent(requestId)}/poll-exchange`, { method: 'POST', body: JSON.stringify({ state }) }, false).then(result => {
      this.setAccessToken(result.accessToken)
      return result
    })
  }

  getRouting(app: MagellokuApp = 'qgis', tier: MagellokuTier = 'balanced') {
    return this.request<{ selected: { modelId: string; configId: string; provider: { id: string; name: string } } }>(`/desktop/routing?app=${app}&tier=${tier}`)
  }

  respondLlm(input: { app: MagellokuApp; tier: MagellokuTier; messages: MagellokuMessage[]; [key: string]: unknown }) {
    return this.request<Record<string, unknown>>('/desktop/llm/respond', { method: 'POST', body: JSON.stringify(input) })
  }
}

export const MAGELLOKU_API_BASE_URL = 'https://api.magelloku.com/api/v1'
