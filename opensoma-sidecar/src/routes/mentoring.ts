import { Hono } from 'hono'
import { z } from 'zod'

import { SidecarError } from '../error_mapping'
import { requireSession } from '../middleware'

const StatusFilter = z.enum(['open', 'closed']).optional()
const TypeFilter = z.enum(['public', 'lecture']).optional()

const CancelBody = z.object({
  apply_sn: z.number().int().positive(),
  qustnr_sn: z.number().int().positive(),
})

export const mentoringRouter = new Hono()

mentoringRouter.use('*', requireSession)

mentoringRouter.get('/', async (c) => {
  const client = c.get('somaClient')

  const status = StatusFilter.parse(c.req.query('status'))
  const type = TypeFilter.parse(c.req.query('type'))
  const search = c.req.query('search')
  const pageRaw = c.req.query('page')
  const page = pageRaw ? Number(pageRaw) : undefined

  if (page !== undefined && (!Number.isInteger(page) || page < 1)) {
    throw new SidecarError(422, 'INVALID_REQUEST', 'page must be a positive integer')
  }

  const options: Parameters<typeof client.mentoring.list>[0] = {}
  if (status) options.status = status
  if (type) options.type = type
  if (search) options.search = { field: 'title', value: search }
  if (page !== undefined) options.page = page

  const result = await client.mentoring.list(options)
  return c.json(result)
})

mentoringRouter.get('/:id', async (c) => {
  const client = c.get('somaClient')
  const id = Number(c.req.param('id'))
  if (!Number.isInteger(id) || id < 1) {
    throw new SidecarError(422, 'INVALID_REQUEST', 'mentoring id must be a positive integer')
  }
  const detail = await client.mentoring.get(id)
  return c.json(detail)
})

/**
 * 신청 후 history를 한 번 더 조회해 apply_sn을 매핑한다.
 *
 * 이유: OpenSoma `apply()`는 `Promise<void>` 반환. apply_sn을 받지 못함.
 * 우리는 cancel 호출에 (apply_sn, qustnr_sn) 둘 다 필요해서 직후 history에서
 * 가장 최근 항목을 우리 신청으로 가정해 apply_sn을 추출한다.
 *
 * 매칭 우선순위:
 *   1. url 쿼리에 ?qustnrSn=:id 가 있으면 그 항목 (가장 안전)
 *   2. 없으면 history page=1의 첫 항목 (단일 사용자 시점에선 신뢰 가능)
 */
mentoringRouter.post('/:id/apply', async (c) => {
  const client = c.get('somaClient')
  const id = Number(c.req.param('id'))
  if (!Number.isInteger(id) || id < 1) {
    throw new SidecarError(422, 'INVALID_REQUEST', 'mentoring id must be a positive integer')
  }

  await client.mentoring.apply(id)

  const history = await client.mentoring.history({ page: 1 })
  const exactMatch = history.items.find((item) => item.url?.includes(`qustnrSn=${id}`))
  const matched = exactMatch ?? history.items[0]

  if (!matched) {
    throw new SidecarError(
      502,
      'APPLY_SN_UNRESOLVED',
      'application succeeded but apply_sn could not be resolved from history',
    )
  }
  if (!exactMatch) {
    // 휴리스틱 fallback — race나 history 정렬 변동 시 잘못된 항목을 선택할 수 있음.
    // 운영자가 모니터링할 수 있도록 경고 로그 남김.
    console.warn('[sidecar] apply_sn fallback used (no exact url match)', {
      qustnr_sn: id,
      candidate_apply_sn: matched.id,
      candidate_title: matched.title,
    })
  }

  return c.json({
    apply_sn: matched.id,
    qustnr_sn: id,
    title: matched.title,
    applied_at: matched.appliedAt,
    application_status: matched.applicationStatus,
    approval_status: matched.approvalStatus,
  })
})

mentoringRouter.post('/cancel', async (c) => {
  const client = c.get('somaClient')
  let body: unknown
  try {
    body = await c.req.json()
  } catch {
    throw new SidecarError(422, 'INVALID_REQUEST', 'invalid JSON body')
  }
  const parsed = CancelBody.safeParse(body)
  if (!parsed.success) {
    throw new SidecarError(
      422,
      'INVALID_REQUEST',
      'apply_sn and qustnr_sn (positive integers) are required',
    )
  }
  await client.mentoring.cancel({
    applySn: parsed.data.apply_sn,
    qustnrSn: parsed.data.qustnr_sn,
  })
  return c.body(null, 204)
})
