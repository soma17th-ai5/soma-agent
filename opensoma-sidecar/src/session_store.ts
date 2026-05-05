import type { SomaClient } from 'opensoma'

interface StoredSession {
  client: SomaClient
  username: string
  createdAt: Date
  lastUsedAt: Date
}

export class SessionStore {
  private readonly map = new Map<string, StoredSession>()

  constructor(private readonly maxAgeMs: number = 1000 * 60 * 60 * 6) {}

  set(sessionId: string, client: SomaClient, username: string): void {
    const now = new Date()
    this.map.set(sessionId, {
      client,
      username,
      createdAt: now,
      lastUsedAt: now,
    })
  }

  get(sessionId: string): SomaClient | null {
    const stored = this.map.get(sessionId)
    if (!stored) return null
    if (Date.now() - stored.createdAt.getTime() > this.maxAgeMs) {
      this.map.delete(sessionId)
      return null
    }
    stored.lastUsedAt = new Date()
    return stored.client
  }

  delete(sessionId: string): boolean {
    return this.map.delete(sessionId)
  }

  size(): number {
    return this.map.size
  }

  /** 만료된 세션 제거. 주기적으로 호출. */
  cleanup(): number {
    const cutoff = Date.now() - this.maxAgeMs
    let removed = 0
    for (const [id, session] of this.map) {
      if (session.createdAt.getTime() < cutoff) {
        this.map.delete(id)
        removed++
      }
    }
    return removed
  }
}

export const sessionStore = new SessionStore()
