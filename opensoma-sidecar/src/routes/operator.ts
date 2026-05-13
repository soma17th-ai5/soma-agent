import { Hono } from 'hono'
import { SomaClient, UserGb, type UserIdentity } from 'opensoma'

import { SidecarError } from '../error_mapping'
import { sessionStore } from '../session_store'

let operatorSessionId: string | null = null

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

export const operatorRouter = new Hono()

operatorRouter.get('/session', async (c) => {
  if (operatorSessionId && sessionStore.get(operatorSessionId)) {
    const client = sessionStore.get(operatorSessionId)
    const identity = await client?.whoami()
    return c.json({
      session_id: operatorSessionId,
      ...identityToJson(identity ?? null),
    })
  }

  const username = process.env.OPERATOR_SOMA_USERNAME
  const password = process.env.OPERATOR_SOMA_PASSWORD
  if (!username || !password) {
    throw new SidecarError(
      503,
      'OPERATOR_SESSION_UNAVAILABLE',
      'operator OpenSoma credentials are not configured',
    )
  }

  const client = new SomaClient({ username, password })
  await client.login()

  operatorSessionId = crypto.randomUUID()
  sessionStore.set(operatorSessionId, client, username)

  const identity = await client.whoami()
  return c.json({
    session_id: operatorSessionId,
    ...identityToJson(identity),
  })
})
