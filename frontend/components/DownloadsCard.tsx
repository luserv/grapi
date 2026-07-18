"use client"
import { useState, useEffect, useRef, useCallback, useMemo } from "react"
import { fetchDownloadsAPI, fetchUserDownloadsAPI, buildDownloadStreamURL, buildDownloadFileURL, checkSessionAPI, type MediaItem } from "@/lib/api"
import { Check, XCircle, X, ArrowLeft, Play, Star, ChevronLeft, ChevronRight } from "lucide-react"

const DL_TTL_HOURS = 24

function groupedEntries(obj: Record<string, MediaItem[]>) {
  return Object.entries(obj || {}).sort((a, b) => b[0].localeCompare(a[0]))
}

function fmtDate(iso: string) {
  if (!iso) return ""
  return new Date(iso).toLocaleDateString("es", { day: "2-digit", month: "long", year: "numeric" })
}

interface LbItem { url: string; isVideo: boolean }
interface Lightbox { items: LbItem[]; idx: number }

export default function DownloadsCard({ sessionId }: { sessionId: string | null }) {
  const [users, setUsers]         = useState<Record<string, any> | null>(null)
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState("")
  const [selectedUser, setSelectedUser] = useState<string | null>(null)
  const [userMedia, setUserMedia] = useState<any>(null)
  const [userLoading, setUserLoading] = useState(false)
  const [userError, setUserError] = useState("")
  const [dlStatus, setDlStatus]   = useState<Record<string, string>>({})
  const [dlActive, setDlActive]   = useState<Record<string, EventSource>>({})
  const [lightbox, setLightbox]   = useState<Lightbox | null>(null)

  useEffect(() => { loadUsers() }, [])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!lightbox) return
      if (e.key === "Escape") setLightbox(null)
      else if (e.key === "ArrowLeft") moveLightbox(-1)
      else if (e.key === "ArrowRight") moveLightbox(1)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [lightbox])

  async function loadUsers() {
    setLoading(true); setError("")
    try {
      const { res, data } = await fetchDownloadsAPI()
      if (!res.ok) throw new Error(data.detail || "Error al cargar descargas")
      setUsers(data.users)
    } catch (e: any) {
      setError(e.message || "No se pudieron cargar las descargas.")
    } finally {
      setLoading(false)
    }
  }

  async function selectUser(username: string) {
    setSelectedUser(username); setUserMedia(null); setUserLoading(true); setUserError("")
    try {
      const { res, data } = await fetchUserDownloadsAPI(username)
      if (!res.ok) throw new Error(data.detail || "Error al cargar medios")
      setUserMedia(data)
    } catch (e: any) {
      setUserError(e.message || "No se pudieron cargar los medios.")
    } finally {
      setUserLoading(false)
    }
  }

  function ageHours(username: string) {
    const info = users?.[username]
    if (!info?.downloaded_at) return null
    return (Date.now() - new Date(info.downloaded_at).getTime()) / 3.6e6
  }

  function isFresh(username: string) {
    const a = ageHours(username)
    return a !== null && a < DL_TTL_HOURS
  }

  function freshLabel(username: string) {
    const a = ageHours(username)
    if (a === null) return ""
    if (a < 1) return "recién"
    if (a < 24) return `hace ${Math.round(a)}h`
    const d = Math.round(a / 24)
    return d === 1 ? "ayer" : `hace ${d}d`
  }

  function stopDownload(username: string) {
    const es = dlActive[username]
    if (es) { es.close(); setDlActive(prev => { const n = {...prev}; delete n[username]; return n }) }
    setDlStatus(prev => {
      const s = prev[username]
      if (s && s !== "✓" && s !== "✗") { const n = {...prev}; delete n[username]; return n }
      return prev
    })
  }

  async function downloadUser(username: string) {
    if (!sessionId) return
    if (isFresh(username)) {
      setDlStatus(prev => ({ ...prev, [username]: `Bajado ${freshLabel(username)} — esperá 24h` }))
      return
    }
    stopDownload(username)
    setDlStatus(prev => ({ ...prev, [username]: "Verificando sesión..." }))
    const alive = await checkSessionAPI(sessionId)
    if (!alive) {
      setDlStatus(prev => ({ ...prev, [username]: "Sesión expirada — iniciá sesión de nuevo" }))
      return
    }
    setDlStatus(prev => ({ ...prev, [username]: "Iniciando..." }))
    const info = users?.[username] || {}
    const es = new EventSource(buildDownloadStreamURL(sessionId, username, info.user_pk))
    setDlActive(prev => ({ ...prev, [username]: es }))

    es.onmessage = (e) => {
      const ev = JSON.parse(e.data)
      switch (ev.type) {
        case "phase":    setDlStatus(p => ({ ...p, [username]: ev.label })); break
        case "total":    setDlStatus(p => ({ ...p, [username]: `${ev.section === "gallery" ? "Galería" : "Historias"}: 0/${ev.total}` })); break
        case "download": setDlStatus(p => ({ ...p, [username]: `${ev.section === "gallery" ? "Galería" : "Historias"}: ${ev.current}/${ev.total}` })); break
        case "done":
          setDlStatus(p => ({ ...p, [username]: "✓" }))
          es.close()
          setDlActive(p => { const n = {...p}; delete n[username]; return n })
          loadUsers()
          if (selectedUser === username) selectUser(username)
          break
        case "fatal_error":
          setDlStatus(p => ({ ...p, [username]: "✗" }))
          es.close()
          setDlActive(p => { const n = {...p}; delete n[username]; return n })
          break
        case "error":
          setDlStatus(p => ({ ...p, [username]: `⚠ ${ev.msg}` })); break
      }
    }
    es.onerror = () => {
      if (dlStatus[username] === "✓" || dlStatus[username] === "✗") return
      setDlStatus(p => ({ ...p, [username]: "✗" }))
      es.close()
      setDlActive(p => { const n = {...p}; delete n[username]; return n })
    }
  }

  function mediaURL(item: MediaItem, username: string, section: string) {
    if (item.filename) return buildDownloadFileURL(username, section, item.filename)
    return item.thumbnail_url || ""
  }

  // Flatten gallery/stories for lightbox navigation
  const galleryFlat = useMemo((): MediaItem[] => {
    if (!userMedia?.gallery) return []
    return groupedEntries(userMedia.gallery).flatMap(([, items]) => items).filter((i: MediaItem) => i.filename)
  }, [userMedia])

  const storiesFlat = useMemo((): MediaItem[] => {
    if (!userMedia?.stories) return []
    return groupedEntries(userMedia.stories).flatMap(([, items]) => items).filter((i: MediaItem) => i.filename)
  }, [userMedia])

  function openLightbox(flatItems: MediaItem[], item: MediaItem, section: string) {
    const username = userMedia.username
    const items: LbItem[] = flatItems.map(i => {
      const url = buildDownloadFileURL(username, section, i.filename!)
      return { url, isVideo: !!i.filename?.endsWith(".mp4") }
    })
    const idx = flatItems.findIndex(i => i.pk === item.pk && i.filename === item.filename)
    if (idx === -1) return
    setLightbox({ items, idx })
  }

  function moveLightbox(delta: number) {
    setLightbox(prev => {
      if (!prev) return prev
      const next = (prev.idx + delta + prev.items.length) % prev.items.length
      return { ...prev, idx: next }
    })
  }

  function btnLabel(username: string) {
    const s = dlStatus[username]
    if (s === "✓") return <><Check size={14} /> Descargado</>
    if (s === "✗") return <><XCircle size={14} /> Error</>
    if (s) return s
    return "Descargar"
  }

  function isDownloading(username: string) {
    const s = dlStatus[username]
    return !!s && s !== "✓" && s !== "✗"
  }

  return (
    <>
      <div className="card card-wide">
        <div className="results-header">
          <h2>{selectedUser ? `@${selectedUser}` : "Descargas locales"}</h2>
          <div className="flex gap-2">
            {selectedUser && <button className="btn-secondary btn-sm" onClick={() => { setSelectedUser(null); setUserMedia(null) }}><ArrowLeft size={14} /> Volver</button>}
            <button className="btn-secondary btn-sm" onClick={loadUsers}>Actualizar</button>
          </div>
        </div>

        {!selectedUser && (
          <>
            {loading && <div className="empty">Cargando descargas...</div>}
            {!loading && error && <div className="empty text-danger">{error}</div>}
            {!loading && !error && (!users || Object.keys(users).length === 0) && (
              <div className="empty">No hay descargas todavía.</div>
            )}
            {!loading && !error && users && Object.keys(users).length > 0 && (
              <div className="flex flex-col gap-[0.4rem]">
                {Object.entries(users).map(([username, info]: [string, any]) => (
                  <div key={username}
                    className="flex items-center bg-field border border-edge-soft rounded-field transition-colors hover:border-edge flex-wrap gap-[0.3rem] px-[0.55rem] py-2 xs:gap-[0.4rem] xs:px-3 xs:py-[0.6rem] sm:flex-nowrap sm:gap-3">
                    <div className="flex-1 flex items-center cursor-pointer min-w-0 flex-wrap gap-[0.15rem] xs:gap-1 sm:flex-nowrap sm:gap-3"
                      onClick={() => selectUser(username)}>
                      <span className="user-link">@{username}</span>
                      <span className="text-faint font-mono whitespace-nowrap text-[0.7rem] xs:text-[0.78rem]">
                        {info.gallery} galería · {info.stories} historias
                      </span>
                      <span className="text-faint ml-0 text-[0.65rem] xs:text-[0.72rem] sm:ml-auto">
                        {(info.downloaded_at || "").slice(0, 10)}
                      </span>
                    </div>
                    {sessionId && (
                      <div className="flex items-center gap-[0.3rem] shrink-0 w-full sm:w-auto">
                        <button
                          className="btn-analizar flex-1 sm:flex-none"
                          disabled={isDownloading(username) || isFresh(username)}
                          title={isFresh(username) ? `Bajado ${freshLabel(username)} — se puede re-bajar después de 24h` : ""}
                          onClick={() => downloadUser(username)}>
                          {isDownloading(username) ? btnLabel(username) : (isFresh(username) ? <><Check size={14} /> {freshLabel(username)}</> : btnLabel(username))}
                        </button>
                        {isDownloading(username) && (
                          <button className="btn-icon" onClick={() => stopDownload(username)} aria-label="Detener"><X size={14} /></button>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {selectedUser && (
          <>
            {userLoading && <div className="empty">Cargando medios...</div>}
            {!userLoading && userError && <div className="empty text-danger">{userError}</div>}
            {!userLoading && userMedia && (
              <>
                {/* Galería */}
                {userMedia.gallery && Object.keys(userMedia.gallery).length > 0 ? (
                  <div className="mt-5">
                    <h3 className="text-base font-semibold mb-3 pb-[0.4rem] border-b border-edge-soft">Galería</h3>
                    {groupedEntries(userMedia.gallery).map(([date, items]) => (
                      <div key={`g-${date}`} className="mb-4">
                        <div className="text-[0.8rem] font-medium text-dim mb-[0.4rem] font-mono">{fmtDate(date)}</div>
                        <div className="grid grid-cols-2 gap-[0.2rem] xxs:grid-cols-[repeat(auto-fill,minmax(70px,1fr))] xxs:gap-1 xs:grid-cols-[repeat(auto-fill,minmax(90px,1fr))] xs:gap-[0.35rem] sm:grid-cols-[repeat(auto-fill,minmax(120px,1fr))] sm:gap-2">
                          {(items as MediaItem[]).map(item => {
                            const url = mediaURL(item, userMedia.username, "gallery")
                            const isVideo = item.filename?.endsWith(".mp4")
                            return (
                              <div key={`${item.pk}${item.filename}`}
                                className="bg-surface border border-edge-soft rounded-field overflow-hidden transition-colors hover:border-edge cursor-pointer"
                                onClick={() => item.filename && openLightbox(galleryFlat, item, "gallery")}>
                                <div className="relative">
                                  {isVideo ? (
                                    <video className="w-full aspect-square object-cover block bg-field"
                                      src={url} preload="metadata" muted playsInline />
                                  ) : (
                                    // eslint-disable-next-line @next/next/no-img-element
                                    <img className="w-full aspect-square object-cover block bg-field"
                                      src={url} alt={item.filename || "Sin descargar"} loading="lazy" />
                                  )}
                                  {isVideo && <span className="post-badge"><Play size={10} /></span>}
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : <div className="empty my-4">Sin galería descargada.</div>}

                {/* Historias */}
                {userMedia.stories && Object.keys(userMedia.stories).length > 0 ? (
                  <div className="mt-5">
                    <h3 className="text-base font-semibold mb-3 pb-[0.4rem] border-b border-edge-soft">Historias</h3>
                    {groupedEntries(userMedia.stories).map(([date, items]) => (
                      <div key={`s-${date}`} className="mb-4">
                        <div className="text-[0.8rem] font-medium text-dim mb-[0.4rem] font-mono">{fmtDate(date)}</div>
                        <div className="grid grid-cols-2 gap-[0.2rem] xxs:grid-cols-[repeat(auto-fill,minmax(70px,1fr))] xxs:gap-1 xs:grid-cols-[repeat(auto-fill,minmax(90px,1fr))] xs:gap-[0.35rem] sm:grid-cols-[repeat(auto-fill,minmax(120px,1fr))] sm:gap-2">
                          {(items as MediaItem[]).map(item => {
                            const url = mediaURL(item, userMedia.username, "stories")
                            const isVideo = item.filename?.endsWith(".mp4")
                            return (
                              <div key={`${item.pk}${item.filename}`}
                                className="bg-surface border border-edge-soft rounded-field overflow-hidden transition-colors hover:border-edge cursor-pointer"
                                onClick={() => item.filename && openLightbox(storiesFlat, item, "stories")}>
                                <div className="relative">
                                  {isVideo ? (
                                    <video className="w-full aspect-square object-cover block bg-field"
                                      src={url} preload="metadata" muted playsInline />
                                  ) : (
                                    // eslint-disable-next-line @next/next/no-img-element
                                    <img className="w-full aspect-square object-cover block bg-field"
                                      src={url} alt={item.filename || "Sin descargar"} loading="lazy" />
                                  )}
                                  {isVideo && <span className="post-badge"><Play size={10} /></span>}
                                  {item.highlight && <span className="post-badge left-[6px] right-auto bg-accent text-accent-ink text-[0.6rem]"><Star size={8} /></span>}
                                </div>
                                {item.highlight && (
                                  <div className="text-[0.68rem] text-faint px-[0.4rem] py-1 whitespace-nowrap overflow-hidden text-ellipsis">{item.highlight}</div>
                                )}
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : <div className="empty my-4">Sin historias descargadas.</div>}

                {sessionId && (
                  <div className="results-header mt-4">
                    <div className="flex items-center gap-[0.3rem] shrink-0 w-full sm:w-auto">
                      <button
                        className="btn-analizar flex-1 sm:flex-none"
                        disabled={isDownloading(userMedia.username) || isFresh(userMedia.username)}
                        onClick={() => downloadUser(userMedia.username)}>
                        {isDownloading(userMedia.username)
                          ? btnLabel(userMedia.username)
                          : (isFresh(userMedia.username) ? <><Check size={14} /> Bajado {freshLabel(userMedia.username)}</> : "Actualizar descargas")}
                      </button>
                      {isDownloading(userMedia.username) && (
                        <button className="btn-icon" onClick={() => stopDownload(userMedia.username)} aria-label="Detener"><X size={14} /></button>
                      )}
                    </div>
                  </div>
                )}
              </>
            )}
          </>
        )}
      </div>

      {/* Lightbox */}
      {lightbox && (() => {
        const { url, isVideo } = lightbox.items[lightbox.idx]
        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/90"
            onClick={() => setLightbox(null)}>
            <button className="chip absolute left-6 z-10 text-xl px-4"
              onClick={e => { e.stopPropagation(); moveLightbox(-1) }}><ChevronLeft size={20} /></button>
            {isVideo ? (
              <video key={url} src={url} controls autoPlay
                className="max-w-[88vw] max-h-[88vh] rounded"
                onClick={e => e.stopPropagation()} />
            ) : (
              // eslint-disable-next-line @next/next/no-img-element
              <img key={url} src={url} alt=""
                className="max-w-[88vw] max-h-[88vh] object-contain rounded cursor-zoom-out"
                onClick={e => e.stopPropagation()} />
            )}
            <button className="chip absolute right-6 z-10 text-xl px-4"
              onClick={e => { e.stopPropagation(); moveLightbox(1) }}><ChevronRight size={20} /></button>
            <span className="absolute bottom-6 text-faint text-sm">
              {lightbox.idx + 1} / {lightbox.items.length}
            </span>
          </div>
        )
      })()}
    </>
  )
}
