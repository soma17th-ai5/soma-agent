import { AuthenticationError } from 'opensoma'

export class SidecarError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message)
    this.name = 'SidecarError'
  }
}

/**
 * 알려진 SDK 에러 타입은 명시적으로 매핑하고, 그 외 Error는 502 UPSTREAM_ERROR로 일괄 처리.
 *
 * 문자열 매칭 휴리스틱은 false positive 가능성이 있어 사용 안 함.
 * (예: "Settings not found in cache" 같은 무관한 메시지가 404로 오분류될 수 있음)
 * 라우트별로 NOT_FOUND·INVALID_CREDENTIALS 등을 던지려면 호출부에서 SidecarError를 직접 throw.
 */
export function toSidecarError(err: unknown): SidecarError {
  if (err instanceof SidecarError) return err

  if (err instanceof AuthenticationError) {
    return new SidecarError(401, 'SESSION_EXPIRED', 'OpenSoma session has expired')
  }

  if (err instanceof Error) {
    return new SidecarError(502, 'UPSTREAM_ERROR', err.message)
  }

  return new SidecarError(500, 'UNKNOWN_ERROR', 'unknown error')
}
