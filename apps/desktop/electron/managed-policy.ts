/** Product boundary for the managed Magelloku desktop. */
export const MANAGED_DISABLED_ROUTE_PATHS = ['/capabilities','/messaging','/webhooks','/cron','/profiles','/agents','/starmap','/command-center'] as const
const DISABLED_MUTATIONS = new Set(['hermes:plugin:installDesktop','hermes:plugin:removeDesktop','hermes:fs:reconcileDesktopPlugins','hermes:config:set','hermes:model:set','hermes:profile:create','hermes:profile:delete'])
function pathname(value: string): string { const raw = String(value || ''); const cut = raw.search(/[?#]/); return cut < 0 ? raw : raw.slice(0, cut) }
export function isManagedRouteAllowed(value: string): boolean { const path = pathname(value); return !MANAGED_DISABLED_ROUTE_PATHS.some(disabled => path === disabled || path.startsWith(`${disabled}/`)) }
export function isManagedMutationAllowed(channel: string): boolean { return !DISABLED_MUTATIONS.has(String(channel || '')) }
export function assertManagedMutationAllowed(channel: string): void { if (!isManagedMutationAllowed(channel)) throw new Error(`Managed desktop mutation denied: ${channel}`) }
export function managedRedirect(value: string): string | null { return isManagedRouteAllowed(value) ? null : '/' }
