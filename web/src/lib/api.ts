import { client } from '@/client/client.gen'

/**
 * Where the api lives, and the one place the generated client is configured.
 *
 * Both the app shell and the meetings view need this: the view names the
 * address in its connection error, and a wrong base url is the most common
 * reason that error appears at all.
 */
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

client.setConfig({ baseUrl: API_BASE })
