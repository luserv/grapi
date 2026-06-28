"use client"
import { useState, useRef, useMemo, useEffect } from "react"
import type { User } from "./api"
import {
  loginAPI, logoutAPI, buildStreamURL,
  startDownloadAllJob, subscribeBulkStream, fetchBulkStatus,
  cancelDownloadAll, checkSessionAPI, fetchCachedUsersAPI,
  fetchSessionsAPI, type SessionEntry,
} from "./api"

// ── useAuth ────────────────────────────────────────────────────────
export function useAuth() {
  const [sessionList, setSessionList] = useState<SessionEntry[]>([])
  const [activeSid, setActiveSid]     = useState<string | null>(null)
  const [loginError, setLoginError]   = useState("")
  const [isLoggingIn, setIsLoggingIn] = useState(false)
  const [needsTwofa, setNeedsTwofa]   = useState(false)

  // Alias de compatibilidad con el resto de la app
  const sessionId  = activeSid
  const loggedUser = sessionList.find(s => s.session_id === activeSid)?.username ?? null

  async function loadSessions() {
    const list = await fetchSessionsAPI()
    setSessionList(list)
    // Auto-seleccionar la primera si no hay ninguna activa todavía
    if (list.length > 0) {
      setActiveSid(prev => prev && list.find(s => s.session_id === prev) ? prev : list[0].session_id)
    }
  }

  useEffect(() => { loadSessions() }, [])

  async function login(params: { username: string; password: string; twofa: string }) {
    if (!params.username || !params.password) {
      setLoginError("Usuario y contraseña son requeridos.")
      return
    }
    setLoginError("")
    setIsLoggingIn(true)
    try {
      const { res, data } = await loginAPI({
        username: params.username,
        password: params.password,
        verification_code: params.twofa,
      })
      if (res.status === 401 && data.detail === "2FA_REQUIRED") {
        setNeedsTwofa(true)
        setLoginError("Ingresa el código 2FA y vuelve a intentar.")
        return
      }
      if (!res.ok) {
        const msgs: Record<string, string> = {
          CHALLENGE_REQUIRED:  "Instagram requiere verificación adicional. Apruébalo desde la app y reintentá.",
          INVALID_CREDENTIALS: "Usuario o contraseña incorrectos.",
        }
        setLoginError(msgs[data.detail] || data.detail || "Error de autenticación.")
        return
      }
      const entry: SessionEntry = { session_id: data.session_id, username: data.username }
      setSessionList(prev => {
        const exists = prev.find(s => s.username === entry.username)
        return exists ? prev.map(s => s.username === entry.username ? entry : s) : [...prev, entry]
      })
      setActiveSid(entry.session_id)
      setLoginError("")
    } catch {
      setLoginError("No se pudo conectar con el servidor.")
    } finally {
      setIsLoggingIn(false)
    }
  }

  function logout(sid?: string) {
    const target = sid ?? activeSid
    if (!target) return
    logoutAPI(target)
    setSessionList(prev => {
      const next = prev.filter(s => s.session_id !== target)
      if (activeSid === target) {
        setActiveSid(next.length > 0 ? next[0].session_id : null)
      }
      return next
    })
  }

  function switchTo(sid: string) {
    if (sessionList.find(s => s.session_id === sid)) setActiveSid(sid)
  }

  return {
    sessionId, loggedUser, sessionList, activeSid,
    loginError, isLoggingIn, needsTwofa,
    login, logout, switchTo, loadSessions,
  }
}

// ── useSearch ──────────────────────────────────────────────────────
export function useSearch() {
  const [allResults, setAllResults]       = useState<User[]>([])
  const [currentTarget, setCurrentTarget] = useState<string | null>(null)
  const [currentModo, setCurrentModo]     = useState("following")
  const [resultsStack, setResultsStack]   = useState<{ results: User[]; title: string }[]>([])
  const [isSearching, setIsSearching]     = useState(false)
  const [status, setStatus]               = useState("")
  const [progressIdx, setProgressIdx]     = useState(0)
  const [progressTotal, setProgressTotal] = useState(0)
  const [resultsSource, setResultsSource] = useState<"cache" | "search" | null>(null)
  const abortRef = useRef<AbortController | EventSource | null>(null)

  // Keep mutable refs so closures inside callbacks see fresh values
  const currentTargetRef = useRef(currentTarget)
  useEffect(() => { currentTargetRef.current = currentTarget }, [currentTarget])
  const allResultsRef = useRef(allResults)
  useEffect(() => { allResultsRef.current = allResults }, [allResults])
  const resultsStackRef = useRef(resultsStack)
  useEffect(() => { resultsStackRef.current = resultsStack }, [resultsStack])

  useEffect(() => () => {
    const ac = abortRef.current
    if (ac) {
      if (ac instanceof EventSource) ac.close()
      else (ac as AbortController).abort()
    }
  }, [])

  const progressPct = useMemo(
    () => progressTotal > 0 ? Math.round(progressIdx / progressTotal * 100) : 0,
    [progressIdx, progressTotal],
  )

  function setTarget(username: string | null) { setCurrentTarget(username) }

  async function loadCached(owner?: string) {
    const users = await fetchCachedUsersAPI(owner)
    if (!users.length) return
    setAllResults(users)
    setResultsSource("cache")
    setStatus(`${users.length.toLocaleString()} usuarios de análisis previos · Buscá para actualizar`)
  }

  function stopSearch(statusMsg?: string) {
    const ac = abortRef.current
    if (ac) {
      if (ac instanceof EventSource) (ac as EventSource).close()
      else (ac as AbortController).abort()
      abortRef.current = null
    }
    setIsSearching(false)
    setStatus(statusMsg ?? "")
    setProgressIdx(0)
    setProgressTotal(0)
  }

  function startSearch(sessionId: string, modo: string, stackTitle = "") {
    if (!sessionId) return
    setCurrentModo(modo)
    const label   = modo === "followers" ? "seguidores" : "seguidos"
    const target  = currentTargetRef.current
    const destino = target ? `@${target}` : "tu cuenta"

    if (target && allResultsRef.current.length > 0) {
      setResultsStack(prev => [...prev, { results: [...allResultsRef.current], title: stackTitle || `${allResultsRef.current.length} resultados` }])
    }

    setAllResults([])
    setProgressIdx(0)
    setProgressTotal(0)
    setResultsSource("search")
    setStatus(`Conectando con Instagram... (${destino})`)
    setIsSearching(true)

    const ac = abortRef.current
    if (ac) {
      if (ac instanceof EventSource) ac.close()
      else ac.abort()
    }

    const es = new EventSource(buildStreamURL(sessionId, modo, target))
    abortRef.current = es as any

    es.onmessage = (e) => {
      const ev = JSON.parse(e.data)
      switch (ev.type) {
        case "connected": break
        case "total":
          setProgressTotal(ev.total)
          const items = ev.total.toLocaleString()
          setStatus(`${items} ${label} de ${destino}. Analizando...`)
          break
        case "usuario":
          setAllResults(prev => [...prev, ev.usuario])
          setProgressIdx(ev.idx)
          setProgressTotal(ev.total)
          break
        case "error":
          setStatus(`⚠ Error usuario ${ev.idx}: ${ev.msg}`)
          break
        case "done":
          setStatus(`Completado. ${ev.total.toLocaleString()} ${label} cargados.`)
          setProgressIdx(ev.total)
          setProgressTotal(ev.total)
          setIsSearching(false)
          es.close()
          if (abortRef.current === es) abortRef.current = null
          break
        case "fatal_error":
          setStatus(`Error: ${ev.msg}`)
          setIsSearching(false)
          es.close()
          if (abortRef.current === es) abortRef.current = null
          break
      }
    }

    es.onerror = () => {
      setIsSearching(false)
      setStatus("Error de conexión con el servidor.")
      es.close()
      if (abortRef.current === es) abortRef.current = null
    }
  }

  function clearResults() {
    setAllResults([])
    setResultsStack([])
    setResultsSource(null)
    setStatus("")
    setCurrentTarget(null)
  }

  function goBack() {
    setResultsStack(prev => {
      if (!prev.length) return prev
      const stack = [...prev]
      const last  = stack.pop()!
      setAllResults(last.results)
      return stack
    })
  }

  return {
    allResults, currentTarget, currentModo, resultsStack, isSearching,
    status, progressIdx, progressTotal, progressPct, resultsSource,
    setTarget, stopSearch, startSearch, goBack, loadCached, clearResults,
  }
}

// ── useTable ───────────────────────────────────────────────────────
export function useTable(allResults: User[]) {
  const [sortCol, setSortCol] = useState("follower_count")
  const [sortDir, setSortDir] = useState(-1)
  const [filters, setFilters] = useState({ pub: false, priv: false, ver: false, kw: "", minFol: 0 })

  const filtered = useMemo(() => {
    const list = allResults.filter(u => {
      if (filters.pub  &&  u.is_private)                        return false
      if (filters.priv && !u.is_private)                        return false
      if (filters.ver  && !u.is_verified)                       return false
      if (filters.minFol > 0 && u.follower_count < filters.minFol) return false
      if (filters.kw) {
        const h = [u.biography, u.full_name, u.username].join(" ").toLowerCase()
        if (!h.includes(filters.kw.toLowerCase())) return false
      }
      return true
    })
    return [...list].sort((a, b) => ((a as any)[sortCol] - (b as any)[sortCol]) * sortDir)
  }, [allResults, filters, sortCol, sortDir])

  function toggleSort(col: string) {
    if (col === sortCol) setSortDir(d => d * -1)
    else { setSortCol(col); setSortDir(-1) }
  }

  function applyFilters(list: User[]) {
    return list.filter(u => {
      if (filters.pub  &&  u.is_private)  return false
      if (filters.priv && !u.is_private)  return false
      if (filters.ver  && !u.is_verified) return false
      if (filters.minFol > 0 && u.follower_count < filters.minFol) return false
      if (filters.kw) {
        const h = [u.biography, u.full_name, u.username].join(" ").toLowerCase()
        if (!h.includes(filters.kw.toLowerCase())) return false
      }
      return true
    })
  }

  function setFilter<K extends keyof typeof filters>(key: K, value: typeof filters[K]) {
    setFilters(prev => ({ ...prev, [key]: value }))
  }

  return { sortCol, sortDir, filters, filtered, toggleSort, applyFilters, setFilter }
}

// ── useBulkDownload ────────────────────────────────────────────────
const LS_KEY = "activeBulkJobId"

interface BulkState {
  running: boolean
  idx: number
  total: number
  current: string
  detail: string
  fileSection: string   // "gallery" | "stories" | ""
  fileCurrent: number
  fileTotal: number
  done: { downloaded: number; skipped: number; failed: number; cancelled: boolean } | null
  error: string
  jobId: string | null
  cancelling: boolean
}

const BULK_INIT: BulkState = {
  running: false, idx: 0, total: 0, current: "", detail: "",
  fileSection: "", fileCurrent: 0, fileTotal: 0,
  done: null, error: "", jobId: null, cancelling: false,
}

export function useBulkDownload(sessionId: string | null, onLogout: () => void) {
  const [bulk, setBulk] = useState<BulkState>(BULK_INIT)
  const abortRef = useRef<AbortController | null>(null)

  function applyEvent(ev: any) {
    setBulk(prev => {
      switch (ev.type) {
        case "snapshot":
          return {
            ...prev,
            total: ev.total, idx: ev.idx,
            current: ev.current || "", detail: ev.detail || "",
            ...(ev.status !== "running" ? {
              done: { downloaded: ev.downloaded, skipped: ev.skipped, failed: ev.failed, cancelled: ev.status === "cancelled" },
              running: false,
              ...(ev.status === "error" ? { error: ev.error || "Error" } : {}),
            } : {}),
          }
        case "bulk_start":   return { ...prev, total: ev.total }
        case "user_start":   return { ...prev, idx: ev.idx, current: ev.username, detail: "iniciando…", fileCurrent: 0, fileTotal: 0, fileSection: "" }
        case "user_skipped": return { ...prev, idx: ev.idx, current: ev.username, detail: `salteado (hace ${ev.age_hours}h)`, fileCurrent: 0, fileTotal: 0, fileSection: "" }
        case "phase":        return ev.scope === "item" ? { ...prev, detail: ev.label } : prev
        case "total":        return ev.scope === "item" ? { ...prev, detail: "", fileSection: ev.section, fileCurrent: 0, fileTotal: ev.total } : prev
        case "download":     return ev.scope === "item" ? { ...prev, detail: "", fileSection: ev.section, fileCurrent: ev.current, fileTotal: ev.total } : prev
        case "user_done":    return { ...prev, detail: `✓ ${ev.new_gallery} galería · ${ev.new_stories} historias`, fileCurrent: 0, fileTotal: 0, fileSection: "" }
        case "user_error":   return { ...prev, detail: `✗ ${ev.msg}`, fileCurrent: 0, fileTotal: 0, fileSection: "" }
        case "resting":      return { ...prev, detail: `descansando ${ev.seconds}s…`, fileCurrent: 0, fileTotal: 0, fileSection: "" }
        case "bulk_done":    return { ...prev, done: ev, current: "", detail: "", fileCurrent: 0, fileTotal: 0, fileSection: "" }
        case "fatal_error":  return { ...prev, error: ev.msg }
        default:             return prev
      }
    })
  }

  async function subscribe(jobId: string) {
    setBulk(prev => ({ ...prev, jobId, running: true }))
    abortRef.current = new AbortController()
    try {
      await subscribeBulkStream(jobId, applyEvent, abortRef.current.signal)
    } catch (e: any) {
      if (e?.name !== "AbortError") setBulk(prev => ({ ...prev, error: e?.message || "Error en el stream." }))
    } finally {
      setBulk(prev => ({ ...prev, running: false, cancelling: false }))
      localStorage.removeItem(LS_KEY)
    }
  }

  async function start(users: { username: string; pk: number }[]) {
    if (!sessionId) { setBulk(prev => ({ ...prev, error: "Iniciá sesión para descargar." })); return }
    if (!users.length) return

    setBulk({ ...BULK_INIT, running: true, total: users.length })

    if (!await checkSessionAPI(sessionId)) {
      setBulk(prev => ({ ...prev, running: false, error: "Sesión expirada — iniciá sesión de nuevo." }))
      onLogout()
      return
    }

    let job: any
    try {
      job = await startDownloadAllJob({ sessionId, users, ttlHours: 24 })
    } catch (e: any) {
      setBulk(prev => ({ ...prev, running: false, error: e?.message || "Error" }))
      return
    }
    localStorage.setItem(LS_KEY, job.job_id)
    subscribe(job.job_id)
  }

  async function cancel() {
    const jobId = bulk.jobId
    if (jobId) {
      setBulk(prev => ({ ...prev, cancelling: true, detail: "cancelando…" }))
      await cancelDownloadAll(jobId)
    } else if (abortRef.current) {
      abortRef.current.abort()
      setBulk(prev => ({ ...prev, running: false }))
    }
  }

  async function resume() {
    const jobId = localStorage.getItem(LS_KEY)
    if (!jobId) return
    const st = await fetchBulkStatus(jobId)
    if (!st) { localStorage.removeItem(LS_KEY); return }
    if (st.status === "running") subscribe(jobId)
    else localStorage.removeItem(LS_KEY)
  }

  function clearDone() { setBulk(prev => ({ ...prev, done: null })) }

  return { bulk, start, cancel, resume, clearDone }
}
