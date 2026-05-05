import { Hono } from 'hono'

import { SidecarError } from '../error_mapping'
import { requireSession } from '../middleware'

// OpenSoma 첨부 파일 호스트 화이트리스트. SSRF 방지를 위해 명시적으로 둔다.
// SDK constants.BASE_URL 과 동일 호스트.
const ALLOWED_ATTACHMENT_HOSTS = new Set(['www.swmaestro.ai'])

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

/**
 * 공지 첨부 파일 다운로드 프록시.
 *
 * OpenSoma 첨부 다운로드는 인증된 세션(JSESSIONID 쿠키)이 필요하므로 FastAPI 앱이
 * 직접 다운로드할 수 없다. 이 엔드포인트는 sidecar가 보관 중인 세션 쿠키를 사용해
 * 첨부를 가져온 뒤 바이너리 응답으로 패스스루한다.
 *
 * - `url` 쿼리: content_html에서 추출한 첨부 anchor의 href (절대 URL).
 * - 화이트리스트(`ALLOWED_ATTACHMENT_HOSTS`)에 속한 호스트만 허용 → SSRF 방지.
 * - 응답: 원본 Content-Type / Content-Disposition 그대로 전달.
 *
 * SDK가 binary download API를 노출하지 않으므로 `client.getSessionData()`에서
 * 세션 쿠키만 꺼내 직접 fetch한다. 향후 SDK가 다운로드 API를 추가하면 마이그레이션.
 *
 * 실측 검증은 첨부가 있는 공지를 만나 수행 (#13 follow-up).
 */
noticeRouter.get('/:id/attachment', async (c) => {
  const client = c.get('somaClient')
  const url = c.req.query('url')
  if (!url) {
    throw new SidecarError(422, 'INVALID_REQUEST', 'url query parameter is required')
  }

  let target: URL
  try {
    target = new URL(url)
  } catch {
    throw new SidecarError(422, 'INVALID_REQUEST', 'url must be a valid absolute URL')
  }
  if (!ALLOWED_ATTACHMENT_HOSTS.has(target.hostname)) {
    throw new SidecarError(422, 'INVALID_REQUEST', `host ${target.hostname} is not allowed`)
  }

  const session = client.getSessionData()
  if (!session.sessionCookie) {
    throw new SidecarError(401, 'SESSION_EXPIRED', 'no active session cookie')
  }

  const upstream = await fetch(target.toString(), {
    method: 'GET',
    headers: {
      Cookie: session.sessionCookie,
      // 일부 OpenSoma 다운로드 엔드포인트는 Referer 검증 → 공지 목록 URL을 명시.
      Referer: 'https://www.swmaestro.ai/sw/mypage/myNotice/list.do',
    },
    redirect: 'follow',
  })

  if (!upstream.ok) {
    throw new SidecarError(
      502,
      'UPSTREAM_ERROR',
      `attachment fetch failed: HTTP ${upstream.status}`,
    )
  }

  const buffer = await upstream.arrayBuffer()
  const contentType = upstream.headers.get('content-type') ?? 'application/octet-stream'
  const disposition = upstream.headers.get('content-disposition')
  const headers: Record<string, string> = { 'Content-Type': contentType }
  if (disposition) {
    headers['Content-Disposition'] = disposition
  }
  return new Response(buffer, { status: 200, headers })
})
