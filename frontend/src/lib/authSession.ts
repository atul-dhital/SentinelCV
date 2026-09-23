let accessToken: string | null = null
let restoreHandler: (() => Promise<string | null>) | null = null
let restorePromise: Promise<string | null> | null = null

const subscribers = new Set<(token: string | null) => void>()

function notifySubscribers() {
  subscribers.forEach((listener) => listener(accessToken))
}

export function getAccessToken(): string | null {
  return accessToken
}

export function hasAccessToken(): boolean {
  return Boolean(accessToken)
}

export function setAccessToken(token: string | null): void {
  accessToken = token?.trim() || null
  notifySubscribers()
}

export function clearAccessToken(): void {
  accessToken = null
  notifySubscribers()
}

export function registerAccessTokenRestorer(
  handler: () => Promise<string | null>,
): void {
  restoreHandler = handler
}

export async function restoreAccessToken(force = false): Promise<string | null> {
  if (restorePromise) {
    return restorePromise
  }
  if (!force && accessToken) {
    return accessToken
  }
  if (!restoreHandler) {
    return accessToken
  }

  restorePromise = (async () => {
    try {
      const restoredToken = await restoreHandler()
      setAccessToken(restoredToken)
      return accessToken
    } catch (err) {
      console.warn('[authSession] restoreAccessToken failed:', err)
      return null
    } finally {
      restorePromise = null
    }
  })()

  return restorePromise
}

export async function ensureAccessToken(): Promise<boolean> {
  return Boolean(await restoreAccessToken())
}

export function subscribeToAccessToken(
  listener: (token: string | null) => void,
): () => void {
  subscribers.add(listener)
  return () => subscribers.delete(listener)
}
