export interface User {
  pk: number
  username: string
  full_name: string | null
  biography: string | null
  follower_count: number
  following_count: number
  media_count: number
  is_verified: boolean
  is_private: boolean
  profile_pic_url_hd: string | null
}

export interface DownloadEntry {
  gallery: number
  stories: number
  highlights: number
  downloaded_at: string | null
  user_pk: number | null
}

export interface MediaItem {
  pk: string | number
  filename: string | null
  taken_at: string
  media_type: number
  highlight?: string
  thumbnail_url?: string
}

export interface Run {
  id: number
  modo: string
  target_username: string | null
  total: number
  from_cache: number
  created_at: string
}

export interface SessionEntry {
  session_id: string
  username: string
}

export async function fetchSessionsAPI(): Promise<SessionEntry[]> {
  try {
    const res = await fetch('/api/sessions')
    if (!res.ok) return []
    const data = await res.json()
    return data.sessions ?? []
  } catch {
    return []
  }
}

export async function loginAPI(params: { username: string; password: string; verification_code: string }) {
  const res = await fetch('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  return { res, data: await res.json() }
}

export function logoutAPI(sessionId: string) {
  return fetch(`/api/logout?session_id=${sessionId}`, { method: 'POST' }).catch(() => {})
}

export async function checkSessionAPI(sessionId: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/session?session_id=${encodeURIComponent(sessionId)}`)
    return res.ok
  } catch {
    return false
  }
}

export function buildStreamURL(sessionId: string, modo: string, targetUsername: string | null) {
  let url = `/api/seguidores/stream?session_id=${encodeURIComponent(sessionId)}&modo=${modo}`
  if (targetUsername) url += `&target_username=${encodeURIComponent(targetUsername)}`
  return url
}

export function buildDownloadStreamURL(sessionId: string, username: string, userId?: number | null, sections?: string) {
  let url = `/api/download-user/stream?session_id=${encodeURIComponent(sessionId)}&username=${encodeURIComponent(username)}`
  if (userId) url += `&user_id=${encodeURIComponent(userId)}`
  if (sections) url += `&sections=${encodeURIComponent(sections)}`
  return url
}

export async function startDownloadAllJob(params: { sessionId: string; users: { username: string; pk: number }[]; ttlHours: number }) {
  const res = await fetch('/api/download-all', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: params.sessionId, users: params.users, ttl_hours: params.ttlHours }),
  })
  if (!res.ok) {
    let detail = 'No se pudo iniciar la descarga masiva.'
    try { detail = (await res.json()).detail || detail } catch {}
    throw new Error(detail)
  }
  return res.json()
}

export async function subscribeBulkStream(jobId: string, onEvent: (ev: any) => void, signal: AbortSignal) {
  const res = await fetch(`/api/download-all/stream?job_id=${encodeURIComponent(jobId)}`, { signal })
  if (!res.ok) throw new Error('No se pudo conectar al job.')
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const chunks = buf.split('\n\n')
    buf = chunks.pop()!
    for (const chunk of chunks) {
      const line = chunk.split('\n').find(l => l.startsWith('data:'))
      if (!line) continue
      try { onEvent(JSON.parse(line.slice(5).trim())) } catch {}
    }
  }
}

export async function fetchBulkStatus(jobId: string) {
  const res = await fetch(`/api/download-all/status?job_id=${encodeURIComponent(jobId)}`)
  return res.ok ? res.json() : null
}

export function cancelDownloadAll(jobId: string) {
  return fetch(`/api/download-all/cancel?job_id=${encodeURIComponent(jobId)}`, { method: 'POST' }).catch(() => {})
}

export async function fetchDownloadsAPI() {
  const res = await fetch('/api/downloads')
  return { res, data: await res.json() }
}

export async function fetchUserDownloadsAPI(username: string) {
  const res = await fetch(`/api/downloads/${encodeURIComponent(username)}`)
  return { res, data: await res.json() }
}

export function buildDownloadFileURL(username: string, section: string, filename: string) {
  return `/api/downloads/${encodeURIComponent(username)}/files/${section}/${encodeURIComponent(filename)}`
}

export async function fetchCachedUsersAPI(owner?: string, limit = 5000): Promise<User[]> {
  let url = `/api/history/users?limit=${limit}`
  if (owner) url += `&owner=${encodeURIComponent(owner)}`
  const res = await fetch(url)
  if (!res.ok) return []
  const data = await res.json()
  return data.users ?? []
}

export async function fetchRunsAPI(sessionId: string, limit = 50) {
  const res = await fetch(`/api/history/runs?session_id=${encodeURIComponent(sessionId)}&limit=${limit}`)
  return { res, data: await res.json() }
}

export async function fetchRunDetailAPI(sessionId: string, runId: number) {
  const res = await fetch(`/api/history/runs/${runId}?session_id=${encodeURIComponent(sessionId)}`)
  return { res, data: await res.json() }
}

export async function fetchDiffAPI(sessionId: string, base: number, compare: number) {
  const res = await fetch(`/api/history/diff?session_id=${encodeURIComponent(sessionId)}&base=${base}&compare=${compare}`)
  return { res, data: await res.json() }
}
