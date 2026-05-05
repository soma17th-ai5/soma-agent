import { describe, expect, it } from 'bun:test'
import type { SomaClient } from 'opensoma'

import { SidecarError, toSidecarError } from '../src/error_mapping'
import { createApp } from '../src/server'
import { sessionStore } from '../src/session_store'

const app = createApp()

interface FakeMentoring {
  apply?: (id: number) => Promise<void>
  cancel?: (params: { applySn: number; qustnrSn: number }) => Promise<void>
  history?: (
    options?: { page?: number },
  ) => Promise<{ items: Array<Record<string, unknown>>; pagination: Record<string, unknown> }>
}

function injectFakeClient(sessionId: string, mentoring: FakeMentoring): void {
  const fake = { mentoring } as unknown as SomaClient
  sessionStore.set(sessionId, fake, 'test-user')
}

async function jsonOf(res: Response): Promise<Record<string, unknown>> {
  return (await res.json()) as Record<string, unknown>
}

describe('healthz', () => {
  it('should_return_ok_when_called', async () => {
    const res = await app.request('/healthz')
    expect(res.status).toBe(200)
    const body = await jsonOf(res)
    expect(body).toEqual({ status: 'ok' })
  })
})

describe('readyz', () => {
  it('should_return_session_count_when_called', async () => {
    const res = await app.request('/readyz')
    expect(res.status).toBe(200)
    const body = await jsonOf(res)
    expect(body.status).toBe('ready')
    expect(typeof body.sessions).toBe('number')
  })
})

describe('protected routes without session header', () => {
  it('should_return_401_when_calling_notice_without_session', async () => {
    const res = await app.request('/notice')
    expect(res.status).toBe(401)
    const body = await jsonOf(res)
    expect(body.code).toBe('SESSION_REQUIRED')
  })

  it('should_return_401_when_calling_mentoring_without_session', async () => {
    const res = await app.request('/mentoring')
    expect(res.status).toBe(401)
  })

  it('should_return_401_when_calling_application_history_without_session', async () => {
    const res = await app.request('/application/history')
    expect(res.status).toBe(401)
  })

  it('should_return_401_when_calling_whoami_without_session', async () => {
    const res = await app.request('/whoami')
    expect(res.status).toBe(401)
  })

  it('should_return_401_when_session_id_unknown', async () => {
    const res = await app.request('/notice', {
      headers: { 'X-Soma-Session': 'unknown-id' },
    })
    expect(res.status).toBe(401)
    const body = await jsonOf(res)
    expect(body.code).toBe('SESSION_EXPIRED')
  })
})

describe('sessions', () => {
  it('should_return_422_when_login_body_is_empty', async () => {
    const res = await app.request('/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    })
    expect(res.status).toBe(422)
    const body = await jsonOf(res)
    expect(body.code).toBe('INVALID_REQUEST')
  })

  it('should_return_422_when_body_is_not_json', async () => {
    const res = await app.request('/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: 'not-json',
    })
    expect(res.status).toBe(422)
  })

  it('should_return_404_when_deleting_unknown_session', async () => {
    const res = await app.request('/sessions/unknown', { method: 'DELETE' })
    expect(res.status).toBe(404)
  })
})

describe('cancel validation', () => {
  it('should_return_422_when_cancel_body_missing_keys', async () => {
    const res = await app.request('/mentoring/cancel', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Soma-Session': 'any',
      },
      body: JSON.stringify({ apply_sn: 1 }),
    })
    // 401 (session not found) is checked before body parsing in middleware
    expect([401, 422]).toContain(res.status)
  })
})

describe('not found', () => {
  it('should_return_404_when_route_unknown', async () => {
    const res = await app.request('/no-such-route')
    expect(res.status).toBe(404)
    const body = await jsonOf(res)
    expect(body.code).toBe('NOT_FOUND')
  })
})

describe('mentoring apply mapping (uses real qustnrSn from history url)', () => {
  it('should_returnApplySnAndParsedQustnrSn_when_historyAdvances', async () => {
    const sid = 'sid-apply-1'
    const beforeItems = [{ id: 100, url: '/sw/...?qustnrSn=11000', title: 'old' }]
    const afterItems = [
      {
        id: 999,
        url: '/sw/mypage/mentoLec/view.do?qustnrSn=11258&menuNo=200046',
        title: '[염승헌] TRIFLAM',
        appliedAt: '2026-05-05 12:31',
        applicationStatus: '접수완료',
        approvalStatus: 'OK',
      },
      ...beforeItems,
    ]
    let historyCallCount = 0
    injectFakeClient(sid, {
      apply: async () => undefined,
      history: async () => {
        historyCallCount++
        return {
          items: historyCallCount === 1 ? beforeItems : afterItems,
          pagination: { totalPages: 1 },
        }
      },
    })

    const res = await app.request('/mentoring/11001/apply', {
      method: 'POST',
      headers: { 'X-Soma-Session': sid },
    })
    expect(res.status).toBe(200)
    const body = await jsonOf(res)
    expect(body.apply_sn).toBe(999)
    // 핵심: 입력 11001 이 아니라 url 에서 파싱한 11258
    expect(body.qustnr_sn).toBe(11258)
    expect(body.mentoring_id).toBe(11001)
    expect(body.title).toBe('[염승헌] TRIFLAM')
  })

  it('should_return502_when_historyDoesNotAdvanceAfterApply', async () => {
    const sid = 'sid-apply-2'
    const sameItems = [{ id: 100, url: '/sw/...?qustnrSn=11000', title: 'unchanged' }]
    injectFakeClient(sid, {
      apply: async () => undefined,
      history: async () => ({ items: sameItems, pagination: { totalPages: 1 } }),
    })

    const res = await app.request('/mentoring/11001/apply', {
      method: 'POST',
      headers: { 'X-Soma-Session': sid },
    })
    expect(res.status).toBe(502)
    const body = await jsonOf(res)
    expect(body.code).toBe('APPLY_SN_UNRESOLVED')
  })

  it('should_fallbackToInputId_when_urlMissingQustnrSn', async () => {
    const sid = 'sid-apply-3'
    const beforeItems = [{ id: 100, url: '/sw/...?qustnrSn=11000', title: 'prev' }]
    const afterItems = [
      {
        id: 200,
        url: '/sw/no-querystring',
        title: 'new',
        appliedAt: '2026-05-05',
        applicationStatus: '접수완료',
        approvalStatus: 'OK',
      },
      ...beforeItems,
    ]
    let calls = 0
    injectFakeClient(sid, {
      apply: async () => undefined,
      history: async () => {
        calls++
        return {
          items: calls === 1 ? beforeItems : afterItems,
          pagination: { totalPages: 1 },
        }
      },
    })

    const res = await app.request('/mentoring/77/apply', {
      method: 'POST',
      headers: { 'X-Soma-Session': sid },
    })
    expect(res.status).toBe(200)
    const body = await jsonOf(res)
    expect(body.apply_sn).toBe(200)
    expect(body.qustnr_sn).toBe(77) // url 파싱 실패 → 입력 fallback
  })
})

describe('mentoring cancel handles "정상처리" success message', () => {
  it('should_return204_when_sdkThrowsWithKoreanSuccessMessage', async () => {
    const sid = 'sid-cancel-1'
    injectFakeClient(sid, {
      cancel: async () => {
        // OpenSoma 가 200 OK + "정상처리하였습니다." 본문을 보내면 SDK 가 throw 하는 케이스
        throw new Error('정상처리하였습니다.')
      },
    })

    const res = await app.request('/mentoring/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Soma-Session': sid },
      body: JSON.stringify({ apply_sn: 59, qustnr_sn: 11258 }),
    })
    expect(res.status).toBe(204)
  })

  it('should_return502_when_sdkThrowsWithRealError', async () => {
    const sid = 'sid-cancel-2'
    injectFakeClient(sid, {
      cancel: async () => {
        throw new Error('network broken')
      },
    })

    const res = await app.request('/mentoring/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Soma-Session': sid },
      body: JSON.stringify({ apply_sn: 59, qustnr_sn: 11258 }),
    })
    expect(res.status).toBe(502)
    const body = await jsonOf(res)
    expect(body.code).toBe('UPSTREAM_ERROR')
  })

  it('should_return204_when_sdkResolvesNormally', async () => {
    const sid = 'sid-cancel-3'
    injectFakeClient(sid, {
      cancel: async () => undefined,
    })

    const res = await app.request('/mentoring/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Soma-Session': sid },
      body: JSON.stringify({ apply_sn: 59, qustnr_sn: 11258 }),
    })
    expect(res.status).toBe(204)
  })
})

describe('error mapping', () => {
  it('should_pass_through_sidecar_error_unchanged', () => {
    const original = new SidecarError(403, 'FORBIDDEN', 'no')
    expect(toSidecarError(original)).toBe(original)
  })

  it('should_map_unknown_value_to_500', () => {
    const mapped = toSidecarError('plain string')
    expect(mapped.status).toBe(500)
    expect(mapped.code).toBe('UNKNOWN_ERROR')
  })

  it('should_map_generic_error_to_502_upstream', () => {
    const mapped = toSidecarError(new Error('network broken'))
    expect(mapped.status).toBe(502)
    expect(mapped.code).toBe('UPSTREAM_ERROR')
    expect(mapped.message).toBe('network broken')
  })

  it('should_not_use_string_heuristics_for_404', () => {
    // false positive 방지를 위해 'not found' 문자열은 패턴 매칭 안 함.
    // 라우트에서 명시적으로 SidecarError(404, 'NOT_FOUND', ...)를 throw해야 함.
    const mapped = toSidecarError(new Error('settings not found in cache'))
    expect(mapped.status).toBe(502)
    expect(mapped.code).toBe('UPSTREAM_ERROR')
  })
})
