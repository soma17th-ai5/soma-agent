import type { Context, Next } from 'hono'
import type { SomaClient } from 'opensoma'

import { SidecarError } from './error_mapping'
import { sessionStore } from './session_store'

export const SOMA_SESSION_HEADER = 'x-soma-session'

declare module 'hono' {
  interface ContextVariableMap {
    somaClient: SomaClient
    sessionId: string
  }
}

/** X-Soma-Session 헤더에서 SomaClient를 꺼내 컨텍스트에 주입. 없으면 401. */
export async function requireSession(c: Context, next: Next): Promise<Response | void> {
  const sessionId = c.req.header(SOMA_SESSION_HEADER)
  if (!sessionId) {
    throw new SidecarError(401, 'SESSION_REQUIRED', `${SOMA_SESSION_HEADER} header missing`)
  }
  const client = sessionStore.get(sessionId)
  if (!client) {
    throw new SidecarError(401, 'SESSION_EXPIRED', 'session not found or expired')
  }
  c.set('somaClient', client)
  c.set('sessionId', sessionId)
  await next()
}
