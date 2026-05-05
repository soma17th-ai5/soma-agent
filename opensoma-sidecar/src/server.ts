import { Hono } from 'hono'
import { logger } from 'hono/logger'

import { toSidecarError } from './error_mapping'
import { applicationRouter } from './routes/application'
import { mentoringRouter } from './routes/mentoring'
import { noticeRouter } from './routes/notice'
import { sessionsRouter, whoamiRouter } from './routes/sessions'
import { sessionStore } from './session_store'

export function createApp(): Hono {
  const app = new Hono()

  app.use('*', logger())

  app.get('/healthz', (c) => c.json({ status: 'ok' }))
  app.get('/readyz', (c) => c.json({ status: 'ready', sessions: sessionStore.size() }))

  app.route('/sessions', sessionsRouter)
  app.route('/', whoamiRouter)
  app.route('/notice', noticeRouter)
  app.route('/mentoring', mentoringRouter)
  app.route('/application', applicationRouter)

  app.onError((err, c) => {
    const e = toSidecarError(err)
    if (e.status >= 500) {
      // err 객체 전체를 직렬화하면 SomaHttp 내부 상태(쿠키 등)가 새어나갈 수 있음.
      // message + stack 만 기록.
      console.error('[sidecar] error', {
        code: e.code,
        message: e.message,
        stack: err instanceof Error ? err.stack : undefined,
      })
    }
    return c.json({ code: e.code, message: e.message }, e.status as never)
  })

  app.notFound((c) => c.json({ code: 'NOT_FOUND', message: 'route not found' }, 404))

  return app
}

const app = createApp()
const port = Number(process.env.SIDECAR_PORT ?? 3000)

// 매 시간 만료 세션 청소
setInterval(() => {
  const removed = sessionStore.cleanup()
  if (removed > 0) {
    console.log(`[sidecar] session cleanup: removed ${removed} expired sessions`)
  }
}, 1000 * 60 * 60).unref()

export default { port, fetch: app.fetch }
