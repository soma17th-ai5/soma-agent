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

function extractQustnrSn(url: string | undefined): number | null {
  if (!url) return null
  const m = url.match(/qustnrSn=(\d+)/)
  return m ? Number.parseInt(m[1] ?? '', 10) || null : null
}

/**
 * 신청 후 history를 한 번 더 조회해 (apply_sn, qustnr_sn) 매핑을 해소한다.
 *
 * **OpenSoma 동작**: 입력 mentoring_id가 user 팀 컨텍스트에서 다른 questionnaire 로
 * 자동 라우팅되는 경우가 있다 (예: id=11001 보냈는데 실제로는 본인 팀의 자유멘토링
 * qustnrSn=11258 에 신청). 따라서 입력 id를 그대로 qustnr_sn으로 반환하면 cancel 호출
 * 시 잘못된 ID 페어가 됨.
 *
 * **올바른 매핑**:
 *   1. apply 직전 history 첫 항목 apply_sn(=`items[0].id`) 저장
 *   2. apply 호출
 *   3. history 재조회 — 첫 항목 id 가 변경됐으면 그게 새 신청
 *      (변경 없으면 즉시 반영 안 된 케이스 — 짧게 대기 후 한 번 더 시도)
 *   4. 새 항목의 url에서 `qustnrSn=N` 파싱 → 응답의 qustnr_sn (cancel 에 사용할 진짜 ID)
 */
mentoringRouter.post('/:id/apply', async (c) => {
  const client = c.get('somaClient')
  const mentoringId = Number(c.req.param('id'))
  if (!Number.isInteger(mentoringId) || mentoringId < 1) {
    throw new SidecarError(422, 'INVALID_REQUEST', 'mentoring id must be a positive integer')
  }

  const before = await client.mentoring.history({ page: 1 })
  const previousLatestApplySn = before.items[0]?.id ?? null

  await client.mentoring.apply(mentoringId)

  let matched = (await client.mentoring.history({ page: 1 })).items[0]
  if (matched && matched.id === previousLatestApplySn) {
    // history 가 즉시 반영되지 않았을 가능성. 한 번만 짧게 대기 후 재조회.
    await new Promise((r) => setTimeout(r, 500))
    matched = (await client.mentoring.history({ page: 1 })).items[0]
  }

  if (!matched || matched.id === previousLatestApplySn) {
    throw new SidecarError(
      502,
      'APPLY_SN_UNRESOLVED',
      'application returned but history did not advance',
    )
  }

  const parsedQustnrSn = extractQustnrSn(matched.url)
  if (parsedQustnrSn === null) {
    console.warn('[sidecar] qustnrSn missing in history url; falling back to input id', {
      url: matched.url,
      input_mentoring_id: mentoringId,
    })
  }

  return c.json({
    apply_sn: matched.id,
    qustnr_sn: parsedQustnrSn ?? mentoringId,
    mentoring_id: mentoringId,
    title: matched.title,
    applied_at: matched.appliedAt,
    application_status: matched.applicationStatus,
    approval_status: matched.approvalStatus,
  })
})

/**
 * OpenSoma `/mypage/userAnswer/cancel.do` 가 처리 성공 시 200 OK + 본문
 * `정상처리하였습니다.` 한국어 안내 메시지를 돌려주는 케이스가 관측됨.
 * SDK 가 이 본문을 (json 파싱 실패로 추정) Error 로 throw 하므로 sidecar 쪽에서
 * 메시지 패턴이 success 시그널이면 204 로 통과시킨다.
 */
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
  try {
    await client.mentoring.cancel({
      applySn: parsed.data.apply_sn,
      qustnrSn: parsed.data.qustnr_sn,
    })
  } catch (err) {
    if (err instanceof Error && /정상처리/.test(err.message)) {
      return c.body(null, 204)
    }
    throw err
  }
  return c.body(null, 204)
})
