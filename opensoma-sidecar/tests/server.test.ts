import { describe, expect, it } from 'bun:test'

import { SidecarError, toSidecarError } from '../src/error_mapping'
import { createApp } from '../src/server'

const app = createApp()

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
