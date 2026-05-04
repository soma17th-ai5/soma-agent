import { Hono } from 'hono'

import { SidecarError } from '../error_mapping'
import { requireSession } from '../middleware'

export const noticeRouter = new Hono()

noticeRouter.use('*', requireSession)

noticeRouter.get('/', async (c) => {
  const client = c.get('somaClient')
  const pageRaw = c.req.query('page')
  const page = pageRaw ? Number(pageRaw) : undefined
  if (page !== undefined && (!Number.isInteger(page) || page < 1)) {
    throw new SidecarError(422, 'INVALID_REQUEST', 'page must be a positive integer')
  }
  const result = await client.notice.list(page === undefined ? undefined : { page })
  return c.json(result)
})

noticeRouter.get('/:id', async (c) => {
  const client = c.get('somaClient')
  const idRaw = c.req.param('id')
  const id = Number(idRaw)
  if (!Number.isInteger(id) || id < 1) {
    throw new SidecarError(422, 'INVALID_REQUEST', 'notice id must be a positive integer')
  }
  const detail = await client.notice.get(id)
  return c.json(detail)
})
