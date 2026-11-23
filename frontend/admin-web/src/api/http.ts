/**
 * Fetch wrapper for the admin API (T7.2). Same-origin paths (nginx proxies them), a bearer
 * token from the session, and one refresh on 401 before the request is retried once.
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`${status}: ${detail}`)
  }
}

export interface TokenSource {
  /** The current access token, or null when logged out. */
  accessToken(): string | null
  /** Gets a new access token with the refresh token; false means the session is over. */
  refresh(): Promise<boolean>
}

export type FetchFn = (input: string, init?: RequestInit) => Promise<Response>

export async function errorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) return body.detail.map((d: { msg?: string }) => d.msg ?? '').join('; ')
  } catch {
    // not JSON
  }
  return response.statusText || 'Request failed'
}

export class HttpClient {
  constructor(
    private readonly tokens: TokenSource,
    private readonly fetchFn: FetchFn = (input, init) => fetch(input, init),
  ) {}

  /** Sends with the bearer token, refreshing once on 401; throws [ApiError] unless 2xx. */
  async send(method: string, path: string, body?: unknown, headers: Record<string, string> = {}): Promise<Response> {
    const attempt = () => {
      const token = this.tokens.accessToken()
      return this.fetchFn(path, {
        method,
        headers: {
          ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          ...headers,
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
      })
    }
    let response = await attempt()
    if (response.status === 401 && (await this.tokens.refresh())) response = await attempt()
    if (!response.ok) throw new ApiError(response.status, await errorDetail(response))
    return response
  }

  async request<T>(method: string, path: string, body?: unknown, headers: Record<string, string> = {}): Promise<T> {
    const response = await this.send(method, path, body, headers)
    if (response.status === 204) return undefined as T
    const type = response.headers.get('Content-Type') ?? ''
    return (type.includes('application/json') ? await response.json() : await response.text()) as T
  }

  get<T>(path: string, headers?: Record<string, string>) {
    return this.request<T>('GET', path, undefined, headers)
  }

  post<T>(path: string, body?: unknown, headers?: Record<string, string>) {
    return this.request<T>('POST', path, body, headers)
  }

  delete<T>(path: string) {
    return this.request<T>('DELETE', path)
  }

  /** A history page: the rows plus `X-Total-Count` (T5.2). */
  async page<T>(path: string): Promise<{ items: T[]; total: number }> {
    const response = await this.send('GET', path)
    const items = (await response.json()) as T[]
    const total = Number(response.headers.get('X-Total-Count'))
    return { items, total: Number.isFinite(total) && response.headers.has('X-Total-Count') ? total : items.length }
  }

  /** Downloads a file (CSV exports) with the server's file name when it sends one. */
  async file(path: string): Promise<{ blob: Blob; name: string | null }> {
    const response = await this.send('GET', path)
    const disposition = response.headers.get('Content-Disposition') ?? ''
    const name = /filename="?([^";]+)"?/i.exec(disposition)?.[1] ?? null
    return { blob: await response.blob(), name }
  }
}

/** Builds `path?k=v` from the defined, non-empty values. */
export function withQuery(path: string, params: Record<string, string | number | null | undefined>): string {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') query.set(key, String(value))
  }
  const text = query.toString()
  return text ? `${path}?${text}` : path
}
