import { HttpClient } from './http'
import { useSession } from '../stores/session'
import type { components } from './schema'

export type Schemas = components['schemas']

let client: HttpClient | null = null

/** The app's API client, bound to the session store (create after Pinia is installed). */
export function api(): HttpClient {
  client ??= new HttpClient(useSession().tokens)
  return client
}
