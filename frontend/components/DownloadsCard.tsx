"use client"
import { useState, useEffect, useRef, useCallback, useMemo } from "react"
import { fetchDownloadsAPI, fetchUserDownloadsAPI, buildDownloadStreamURL, buildDownloadFileURL, checkSessionAPI, type MediaItem } from "@/lib/api"
import { formatDownloadSummary, sectionLabel, type DownloadDoneEvent } from "@/lib/downloadSummary"
import { X, ArrowLeft, Play, Star, ChevronLeft, ChevronRight, AlertTriangle } from "lucide-react"

function groupedEntries(obj: Record<string, MediaItem[]>) {
  return Object.entries(obj || {}).sort((a, b) => b[0].localeCompare(a[0]))
}

function fmtDate(iso: string) {
  if (!iso) return ""
  return new Date(iso).toLocaleDateString("es", { day: "2-digit", month: "long", year: "numeric" })
}

interface LbItem { url: string; isVideo: boolean }
interface Lightbox { items: LbItem[]; idx: number }

/** Línea de estado persistente por usuario: hint de última bajada, resumen
 * por sección de la última descarga completada, y errores no fatales
 * acumulados durante la corrida (no fatales = no cortan la descarga). */
function DownloadStatusLine({
  isDownloading, freshLabel, hasFreshLabel, fatal, done, errors,
}: {
  username: string
  isDownloading: boolean
  freshLabel: string
  hasFreshLabel: boolean
  fatal?: string
  done?: DownloadDoneEvent
  errors?: string[]
}) {
  const showDone = !isDownloading && done
  if (!hasFreshLabel && !fatal && !showDone && !errors?.length) return null
  return (
    <div className="flex flex-col gap-[0.15rem] font-mono text-[0.68rem] xs:text-[0.72rem]">
      {hasFreshLabel && !isDownloading && !showDone && (
        <span className="text-faint">Bajado {freshLabel}</span>
      )}
      {fatal && (
        <span className="text-danger inline-flex items-center gap-1"><AlertTriangle size={12} /> {fatal}</span>
      )}
      {showDone && (
        <div className="flex flex-wrap gap-x-2 gap-y-[0.1rem]">
          {formatDownloadSummary(done).map((seg, i) => (
            <span key={i} className={seg.danger ? "text-danger inline-flex items-center gap-1" : "text-dim"}>
              {seg.danger && <AlertTriangle size={11} />}{seg.text}
            </span>
          ))}
        </div>
      )}
      {errors && errors.length > 0 && (
        <div className="flex flex-col gap-[0.1rem]">
          {errors.map((msg, i) => (
            <span key={i} className="text-danger inline-flex items-center gap-1"><AlertTriangle size={11} /> {msg}</span>
          ))}
        </div>
      )}
    </div>
  )
}

export default function DownloadsCard({ sessionId }: { sessionId: string | null }) {
  const [users, setUsers]         = useState<Record<string, any> | null>(null)
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState("")
  const [selectedUser, setSelectedUser] = useState<string | null>(null)
  const [userMedia, setUserMedia] = useState<any>(null)
  const [userLoading, setUserLoading] = useState(false)
  const [userError, setUserError] = useState("")
  // Progreso transitorio mientras hay una descarga activa (fase/total/current).
  const [dlProgress, setDlProgress] = useState<Record<string, string>>({})
  // Error fatal (aborta la descarga); se limpia solo a los pocos segundos.
  const [dlFatal, setDlFatal]     = useState<Record<string, string>>({})
  // Resumen persistente de la última descarga completada (no se borra solo).
  const [dlDone, setDlDone]       = useState<Record<string, DownloadDoneEvent>>({})
  // Errores no fatales acumulados durante la corrida actual (últimos 3).
  const [dlErrors, setDlErrors]   = useState<Record<string, string[]>>({})
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
    setDlProgress(prev => { const n = {...prev}; delete n[username]; return n })
  }

  // El backend dedupea contra disco (_existing_pks); no hay bloqueo de 24h acá,
  // una segunda corrida solo baja lo que falte.
  async function downloadUser(username: string) {
    if (!sessionId) return
    stopDownload(username)
    setDlFatal(prev => { const n = {...prev}; delete n[username]; return n })
    setDlErrors(prev => { const n = {...prev}; delete n[username]; return n })
    setDlProgress(prev => ({ ...prev, [username]: "Verificando sesión..." }))
    const alive = await checkSessionAPI(sessionId)
    if (!alive) {
      setDlProgress(prev => { const n = {...prev}; delete n[username]; return n })
      setDlFatal(prev => ({ ...prev, [username]: "Sesión expirada — iniciá sesión de nuevo" }))
      return
    }
    setDlProgress(prev => ({ ...prev, [username]: "Iniciando..." }))
    const info = users?.[username] || {}
    const es = new EventSource(buildDownloadStreamURL(sessionId, username, info.user_pk))
    setDlActive(prev => ({ ...prev, [username]: es }))
    let settled = false

    es.onmessage = (e) => {
      const ev = JSON.parse(e.data)
      switch (ev.type) {
        case "phase":    setDlProgress(p => ({ ...p, [username]: ev.label })); break
        case "total":    setDlProgress(p => ({ ...p, [username]: `${sectionLabel(ev.section)}: 0/${ev.total}` })); break
        case "download": setDlProgress(p => ({ ...p, [username]: `${sectionLabel(ev.section)}: ${ev.current}/${ev.total}` })); break
        case "done":
          settled = true
          setDlDone(p => ({ ...p, [username]: ev as DownloadDoneEvent }))
          setDlProgress(p => { const n = {...p}; delete n[username]; return n })
          es.close()
          setDlActive(p => { const n = {...p}; delete n[username]; return n })
          loadUsers()
          if (selectedUser === username) selectUser(username)
          break
        case "fatal_error":
          settled = true
          setDlFatal(p => ({ ...p, [username]: ev.msg }))
          setDlProgress(p => { const n = {...p}; delete n[username]; return n })
          es.close()
          setDlActive(p => { const n = {...p}; delete n[username]; return n })
          setTimeout(() => setDlFatal(p => { const n = {...p}; delete n[username]; return n }), 4000)
          break
        case "error":
          setDlErrors(p => ({ ...p, [username]: [...(p[username] || []), ev.msg].slice(-3) })); break
      }
    }
    es.onerror = () => {
      if (settled) return
      settled = true
      setDlFatal(p => ({ ...p, [username]: "Error de conexión" }))
      setDlProgress(p => { const n = {...p}; delete n[username]; return n })
      es.close()
      setDlActive(p => { const n = {...p}; delete n[username]; return n })
      setTimeout(() => setDlFatal(p => { const n = {...p}; delete n[username]; return n }), 4000)
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

  const highlightsFlat = useMemo((): MediaItem[] => {
    if (!userMedia?.highlights) return []
    return Object.values(userMedia.highlights).flatMap((items: any) => items).filter((i: MediaItem) => i.filename)
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

  function isDownloading(username: string) {
    return !!dlActive[username]
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
                    className="flex flex-col gap-[0.3rem] bg-field border border-edge-soft rounded-field transition-colors hover:border-edge px-[0.55rem] py-2 xs:px-3 xs:py-[0.6rem]">
                    <div className="flex items-center flex-wrap gap-[0.3rem] xs:gap-[0.4rem] sm:flex-nowrap sm:gap-3">
                      <div className="flex-1 flex items-center cursor-pointer min-w-0 flex-wrap gap-[0.15rem] xs:gap-1 sm:flex-nowrap sm:gap-3"
                        onClick={() => selectUser(username)}>
                        <span className="user-link">@{username}</span>
                        <span className="text-faint font-mono whitespace-nowrap text-[0.7rem] xs:text-[0.78rem]">
                          {info.gallery} galería · {info.stories} historias · {info.highlights || 0} destacadas
                        </span>
                        <span className="text-faint ml-0 text-[0.65rem] xs:text-[0.72rem] sm:ml-auto">
                          {(info.downloaded_at || "").slice(0, 10)}
                        </span>
                      </div>
                      {sessionId && (
                        <div className="flex items-center gap-[0.3rem] shrink-0 w-full sm:w-auto">
                          <button
                            className="btn-analizar flex-1 sm:flex-none min-h-[44px]"
                            disabled={isDownloading(username)}
                            onClick={() => downloadUser(username)}>
                            {isDownloading(username) ? (dlProgress[username] || "Iniciando...") : "Descargar nuevos"}
                          </button>
                          {isDownloading(username) && (
                            <button className="btn-icon min-h-[44px] min-w-[44px]" onClick={() => stopDownload(username)} aria-label="Detener"><X size={14} /></button>
                          )}
                        </div>
                      )}
                    </div>
                    <DownloadStatusLine
                      username={username}
                      isDownloading={isDownloading(username)}
                      freshLabel={freshLabel(username)}
                      hasFreshLabel={ageHours(username) !== null}
                      fatal={dlFatal[username]}
                      done={dlDone[username]}
                      errors={dlErrors[username]}
                    />
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

                {/* Historias destacadas */}
                {userMedia.highlights && Object.keys(userMedia.highlights).length > 0 ? (
                  <div className="mt-5">
                    <h3 className="text-base font-semibold mb-3 pb-[0.4rem] border-b border-edge-soft">Destacadas</h3>
                    {Object.entries(userMedia.highlights).sort(([a], [b]) => a.localeCompare(b)).map(([title, items]) => (
                      <div key={`h-${title}`} className="mb-4">
                        <div className="text-[0.8rem] font-medium text-dim mb-[0.4rem] font-mono flex items-center gap-1">
                          <Star size={12} className="text-accent" /> {title}
                        </div>
                        <div className="grid grid-cols-2 gap-[0.2rem] xxs:grid-cols-[repeat(auto-fill,minmax(70px,1fr))] xxs:gap-1 xs:grid-cols-[repeat(auto-fill,minmax(90px,1fr))] xs:gap-[0.35rem] sm:grid-cols-[repeat(auto-fill,minmax(120px,1fr))] sm:gap-2">
                          {(items as MediaItem[]).map(item => {
                            const url = mediaURL(item, userMedia.username, "highlights")
                            const isVideo = item.filename?.endsWith(".mp4")
                            return (
                              <div key={`${item.pk}${item.filename}`}
                                className="bg-surface border border-edge-soft rounded-field overflow-hidden transition-colors hover:border-edge cursor-pointer"
                                onClick={() => item.filename && openLightbox(highlightsFlat, item, "highlights")}>
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
                ) : null}

                {sessionId && (
                  <div className="results-header mt-4">
                    <div className="flex flex-col gap-[0.35rem] w-full sm:w-auto">
                      <div className="flex items-center gap-[0.3rem] shrink-0 w-full sm:w-auto">
                        <button
                          className="btn-analizar flex-1 sm:flex-none min-h-[44px]"
                          disabled={isDownloading(userMedia.username)}
                          onClick={() => downloadUser(userMedia.username)}>
                          {isDownloading(userMedia.username)
                            ? (dlProgress[userMedia.username] || "Iniciando...")
                            : "Actualizar descargas"}
                        </button>
                        {isDownloading(userMedia.username) && (
                          <button className="btn-icon min-h-[44px] min-w-[44px]" onClick={() => stopDownload(userMedia.username)} aria-label="Detener"><X size={14} /></button>
                        )}
                      </div>
                      <DownloadStatusLine
                        username={userMedia.username}
                        isDownloading={isDownloading(userMedia.username)}
                        freshLabel={freshLabel(userMedia.username)}
                        hasFreshLabel={ageHours(userMedia.username) !== null}
                        fatal={dlFatal[userMedia.username]}
                        done={dlDone[userMedia.username]}
                        errors={dlErrors[userMedia.username]}
                      />
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
