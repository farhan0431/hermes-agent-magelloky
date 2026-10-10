import { MagellokuClient, type MagellokuApp, type MagellokuLlmInput, type MagellokuMessage, type MagellokuStreamEvent, type MagellokuTier } from './magelloku-client'

export type MagellokuRuntimeOptions = {
  client?: MagellokuClient
  loadToken?: () => string | null | Promise<string | null>
  saveToken?: (token: string | null) => void | Promise<void>
  openExternal?: (url: string) => void | Promise<void>
  pollIntervalMs?: number
  sleep?: (milliseconds: number) => Promise<void>
}

export type MagellokuAuthState = { status: 'signed_out' | 'pending' | 'signed_in'; user?: { id: string; name: string; email: string } }

export class MagellokuRuntime {
  readonly client: MagellokuClient
  private readonly loadToken?: MagellokuRuntimeOptions['loadToken']
  private readonly saveToken?: MagellokuRuntimeOptions['saveToken']
  private readonly openExternal?: MagellokuRuntimeOptions['openExternal']
  private readonly pollIntervalMs: number
  private readonly sleep: (milliseconds: number) => Promise<void>
  private authState: MagellokuAuthState = { status: 'signed_out' }

  constructor(options: MagellokuRuntimeOptions = {}) {
    this.client = options.client ?? new MagellokuClient()
    this.loadToken = options.loadToken
    this.saveToken = options.saveToken
    this.openExternal = options.openExternal
    this.pollIntervalMs = options.pollIntervalMs ?? 1_000
    this.sleep = options.sleep ?? (milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)))
  }

  getAuthState() { return this.authState }

  async restore() {
    const token = await this.loadToken?.()
    this.client.setAccessToken(token ?? null)
    this.authState = token ? { status: 'signed_in' } : { status: 'signed_out' }
    return this.authState
  }

  async signIn(input: { app?: MagellokuApp; name?: string; platform?: string; waitForCode?: (requestId: string, state: string) => Promise<string> } = {}) {
    const auth = await this.client.startBrowserAuth({ app: input.app ?? 'qgis', name: input.name ?? 'Magelloku AI Desktop', platform: input.platform ?? 'desktop', redirectUri: 'bajiki://desktop/auth/callback' })
    this.authState = { status: 'pending' }
    await this.openExternal?.(auth.authorizeUrl)
    const code = await input.waitForCode?.(auth.requestId, auth.state)
    if (!code) throw new Error('Magelloku browser login did not return an authorization code.')
    const grant = await this.client.exchangeApprovedBrowserGrant(auth.requestId, auth.state, code)
    await this.saveToken?.(grant.accessToken)
    this.authState = { status: 'signed_in', user: grant.user }
    return this.authState
  }

  async signOut() {
    this.client.setAccessToken(null)
    await this.saveToken?.(null)
    this.authState = { status: 'signed_out' }
  }

  async stream(input: { idempotencyKey: string; messages: MagellokuMessage[]; app?: MagellokuApp; modelTier?: MagellokuTier; [key: string]: unknown }, onEvent: (event: MagellokuStreamEvent) => void, signal?: AbortSignal) {
    const payload: MagellokuLlmInput = { ...input, app: input.app ?? 'qgis', modelTier: input.modelTier ?? 'balanced' }
    return this.client.streamLlm(payload, onEvent, signal)
  }

  static messagesFromTranscript(messages: readonly MagellokuMessage[]) { return messages.map(message => ({ ...message })) }
}
