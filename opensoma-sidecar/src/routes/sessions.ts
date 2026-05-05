import { Hono } from 'hono'
import { SomaClient, UserGb, type UserIdentity } from 'opensoma'
import { z } from 'zod'

import { SidecarError } from '../error_mapping'
import { requireSession } from '../middleware'
import { sessionStore } from '../session_store'

const LoginBody = z.object({
  username: z.string().min(1),
  password: z.string().min(1),
})

function mapRole(userGb: UserGb | undefined): 'TRAINEE' | 'MENTOR' | null {
  if (userGb === UserGb.Trainee) return 'TRAINEE'
  if (userGb === UserGb.Mentor) return 'MENTOR'
  return null
}

function identityToJson(identity: UserIdentity | null) {
  if (!identity) return null
  return {
    soma_user_id: identity.userId,
    user_name: identity.userNm,
    user_no: identity.userNo,
    role: mapRole(identity.userGb),
  }
}

export const sessionsRouter = new Hono()

sessionsRouter.post('/', async (c) => {
  let body: unknown
  try {
    body = await c.req.json()
  } catch {
    throw new SidecarError(422, 'INVALID_REQUEST', 'invalid JSON body')
  }
  const parsed = LoginBody.safeParse(body)
  if (!parsed.success) {
    throw new SidecarError(422, 'INVALID_REQUEST', 'username and password are required')
  }

  const { username, password } = parsed.data
  const client = new SomaClient({ username, password })

  // 호출부에서 명시적으로 INVALID_CREDENTIALS 매핑.
  // (글로벌 error_mapping은 문자열 휴리스틱을 쓰지 않음 — false positive 회피)
  try {
    await client.login()
  } catch (err) {
    if (err instanceof Error && /password|login|credential/i.test(err.message)) {
      throw new SidecarError(401, 'INVALID_CREDENTIALS', 'login failed')
    }
    throw err
  }

  const sessionId = crypto.randomUUID()
  sessionStore.set(sessionId, client, username)

  const identity = await client.whoami()
  return c.json({
    session_id: sessionId,
    ...identityToJson(identity),
  })
})

sessionsRouter.delete('/:id', (c) => {
  const removed = sessionStore.delete(c.req.param('id'))
  return c.body(null, removed ? 204 : 404)
})

export const whoamiRouter = new Hono()

whoamiRouter.use('/whoami', requireSession)
whoamiRouter.get('/whoami', async (c) => {
  const client = c.get('somaClient')
  const identity = await client.whoami()
  if (!identity) {
    throw new SidecarError(401, 'SESSION_EXPIRED', 'session is no longer valid')
  }
  return c.json(identityToJson(identity))
})
