import { Hono } from 'hono'

import { SidecarError } from '../error_mapping'
import { requireSession } from '../middleware'

export const applicationRouter = new Hono()

applicationRouter.use('*', requireSession)

applicationRouter.get('/history', async (c) => {
  const client = c.get('somaClient')
  const pageRaw = c.req.query('page')
  const page = pageRaw ? Number(pageRaw) : undefined
  if (page !== undefined && (!Number.isInteger(page) || page < 1)) {
    throw new SidecarError(422, 'INVALID_REQUEST', 'page must be a positive integer')
  }
  const result = await client.mentoring.history(page === undefined ? undefined : { page })
  return c.json(result)
})
