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

export function toSidecarError(err: unknown): SidecarError {
  if (err instanceof SidecarError) return err

  if (err instanceof AuthenticationError) {
    return new SidecarError(401, 'SESSION_EXPIRED', 'OpenSoma session has expired')
  }

  if (err instanceof Error) {
    const msg = err.message.toLowerCase()
    if (msg.includes('not found') || msg.includes('찾을 수 없')) {
      return new SidecarError(404, 'NOT_FOUND', err.message)
    }
    if (msg.includes('login') && msg.includes('fail')) {
      return new SidecarError(401, 'INVALID_CREDENTIALS', 'login failed')
    }
    return new SidecarError(502, 'UPSTREAM_ERROR', err.message)
  }

  return new SidecarError(500, 'UNKNOWN_ERROR', 'unknown error')
}
