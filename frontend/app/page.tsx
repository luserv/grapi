"use client"
import { useState, useEffect, useRef } from "react"
import { useAuth, useSearch, useTable, useBulkDownload } from "@/lib/hooks"
import { buildDownloadStreamURL } from "@/lib/api"
import { formatDownloadSummary, sectionLabel, type DownloadDoneEvent } from "@/lib/downloadSummary"
import { X, Plus } from "lucide-react"
import LoginCard     from "@/components/LoginCard"
import SearchCard    from "@/components/SearchCard"
import ResultsCard   from "@/components/ResultsCard"
import DownloadsCard from "@/components/DownloadsCard"
import HistoryCard   from "@/components/HistoryCard"

type View = "downloads" | "search" | "history"

export default function App() {
  const auth   = useAuth()
  const search = useSearch()
  const table  = useTable(search.allResults)
  const bulk   = useBulkDownload(auth.sessionId, auth.logout)
  const [view, setView]           = useState<View>("search")
  const [showLogin, setShowLogin] = useState(false)

  // Per-user download state
  const [downloadStatus, setDownloadStatus] = useState<Record<string, string>>({})
  const [downloadLabel, setDownloadLabel]   = useState<Record<string, string>>({})
  const activeDownloads = useRef<Record<string, EventSource>>({})

  useEffect(() => { bulk.resume() }, [])

  // Al cambiar de sesión activa: limpiar resultados y cargar caché de esa cuenta
  useEffect(() => {
    search.stopSearch()
    search.clearResults()
    if (auth.sessionId) search.loadCached(auth.loggedUser ?? undefined)
    setShowLogin(false)
  }, [auth.sessionId])

  function stopDownload(username: string) {
    const es = activeDownloads.current[username]
    if (es) { es.close(); delete activeDownloads.current[username] }
    setDownloadStatus(prev => {
      if (prev[username] !== "downloading") return prev
      const n = { ...prev }; delete n[username]; return n
    })
    setDownloadLabel(prev => { const n = { ...prev }; n[username] = ""; return n })
  }

  // Limpia el error tras 3s, salvo que ya haya arrancado otra descarga del mismo usuario.
  function clearErrorLater(username: string) {
    setTimeout(() => {
      if (activeDownloads.current[username]) return
      setDownloadStatus(p => {
        if (p[username] !== "error") return p
        const n = { ...p }; delete n[username]; return n
      })
      setDownloadLabel(p => { const n = { ...p }; delete n[username]; return n })
    }, 3000)
  }

  function handleDownload(username: string, userId: number, sections?: string) {
    if (!auth.sessionId) return
    stopDownload(username)
    const es = new EventSource(buildDownloadStreamURL(auth.sessionId, username, userId, sections))
    activeDownloads.current[username] = es
    setDownloadStatus(prev => ({ ...prev, [username]: "downloading" }))
    setDownloadLabel(prev => ({ ...prev, [username]: "Iniciando..." }))

    es.onmessage = (e) => {
      const ev = JSON.parse(e.data)
      switch (ev.type) {
        case "phase":
          setDownloadLabel(p => ({ ...p, [username]: ev.label })); break
        case "total":
          setDownloadLabel(p => ({ ...p, [username]: `${sectionLabel(ev.section)}: 0/${ev.total}` })); break
        case "download":
          setDownloadLabel(p => ({ ...p, [username]: `${sectionLabel(ev.section)}: ${ev.current}/${ev.total}` })); break
        case "done": {
          const segments = formatDownloadSummary(ev as DownloadDoneEvent)
          setDownloadStatus(p => ({ ...p, [username]: "ok" }))
          setDownloadLabel(p => ({ ...p, [username]: segments.map(s => s.text).join(" · ") }))
          es.close(); delete activeDownloads.current[username]; break
        }
        case "fatal_error":
          setDownloadStatus(p => ({ ...p, [username]: "error" }))
          setDownloadLabel(p => ({ ...p, [username]: `Error: ${ev.msg}` }))
          es.close(); delete activeDownloads.current[username]
          clearErrorLater(username)
          break
        case "error":
          setDownloadLabel(p => ({ ...p, [username]: `Error: ${ev.msg}` })); break
      }
    }
    es.onerror = () => {
      setDownloadStatus(p => ({ ...p, [username]: "error" }))
      setDownloadLabel(p => ({ ...p, [username]: "Error de conexión" }))
      es.close(); delete activeDownloads.current[username]
      clearErrorLater(username)
    }
  }

  function handleLogout(sid?: string) {
    // Detener descargas activas solo si es la sesión activa
    if (!sid || sid === auth.sessionId) {
      for (const username of Object.keys(activeDownloads.current)) stopDownload(username)
      search.stopSearch()
    }
    auth.logout(sid)
  }

  function handleSearch(modo: string) {
    if (search.isSearching || !auth.sessionId) return
    search.startSearch(auth.sessionId, modo)
  }

  function handleCancelSearch() {
    search.stopSearch()
  }

  function handleExportCsv() {
    const rows = table.applyFilters(search.allResults)
    if (!rows.length) return
    const header = "usuario,nombre,seguidores,siguiendo,posts,verificado,privado\n"
    const body   = rows.map(u =>
      `${u.username},"${(u.full_name || "").replace(/"/g, '""')}",${u.follower_count},${u.following_count},${u.media_count},${u.is_verified ? "sí" : "no"},${u.is_private ? "sí" : "no"}`
    ).join("\n")
    const a = document.createElement("a")
    a.href = URL.createObjectURL(new Blob([header + body], { type: "text/csv;charset=utf-8;" }))
    a.download = "resultados.csv"
    a.click()
  }

  const noSessions = auth.sessionList.length === 0

  return (
    <>
      <nav className="tabs">
        <button className={`tab${view === "downloads" ? " on" : ""}`} onClick={() => setView("downloads")}>Descargas</button>
        <button className={`tab${view === "search" ? " on" : ""}`} onClick={() => setView("search")}>Buscar</button>
        {auth.sessionId && (
          <button className={`tab${view === "history" ? " on" : ""}`} onClick={() => setView("history")}>Historial</button>
        )}

        {/* Switcher de cuentas */}
        <div className="ml-auto flex items-center gap-1 pl-2">
          {auth.sessionList.map(s => (
            <div key={s.session_id} className="flex items-center">
              <button
                className={`tab text-[0.78rem] px-[0.55rem]${s.session_id === auth.activeSid ? " on" : ""}`}
                onClick={() => auth.switchTo(s.session_id)}
                title={`Cambiar a @${s.username}`}
              >@{s.username}</button>
              <button
                className="text-faint hover:text-ink text-[0.7rem] px-[0.2rem] leading-none"
                onClick={() => handleLogout(s.session_id)}
                title={`Cerrar sesión de @${s.username}`}
              ><X size={14} /></button>
            </div>
          ))}
          <button
            className={`tab text-[0.82rem] px-[0.55rem]${showLogin && !noSessions ? " on" : ""}`}
            onClick={() => setShowLogin(v => !v)}
            title="Agregar cuenta"
          ><Plus size={14} /></button>
        </div>
      </nav>

      {/* Login: se muestra si no hay sesiones, o si el usuario clickeó "+" */}
      {(noSessions || showLogin) && view !== "downloads" && (
        <LoginCard
          loginError={auth.loginError}
          isLoggingIn={auth.isLoggingIn}
          needsTwofa={auth.needsTwofa}
          onLogin={auth.login}
        />
      )}

      {view === "downloads" && <DownloadsCard sessionId={auth.sessionId} />}

      {auth.sessionId && view === "search" && (
        <>
          <SearchCard
            loggedUser={auth.loggedUser!}
            isSearching={search.isSearching}
            progressIdx={search.progressIdx}
            progressTotal={search.progressTotal}
            progressPct={search.progressPct}
            status={search.status}
            currentTarget={search.currentTarget}
            onSearch={handleSearch}
            onCancel={handleCancelSearch}
            onLogout={() => handleLogout()}
            onClearTarget={() => search.setTarget(null)}
          />
          {(search.allResults.length > 0 || search.isSearching) && (
            <ResultsCard
              allResults={search.allResults}
              isSearching={search.isSearching}
              sessionId={auth.sessionId}
              filters={table.filters}
              filtered={table.filtered}
              sortCol={table.sortCol}
              setFilter={table.setFilter}
              toggleSort={table.toggleSort}
              applyFilters={table.applyFilters}
              bulk={bulk.bulk}
              downloadStatus={downloadStatus}
              downloadLabel={downloadLabel}
              onExportCsv={handleExportCsv}
              onDownload={handleDownload}
              onStopDownload={stopDownload}
              onStartBulk={bulk.start}
              onCancelBulk={bulk.cancel}
              onClearBulkDone={bulk.clearDone}
            />
          )}
        </>
      )}

      {auth.sessionId && view === "history" && <HistoryCard sessionId={auth.sessionId} />}
    </>
  )
}
