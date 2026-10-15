"use client"
import { useState, useEffect, useMemo } from "react"
import { API_BASE, fetchDownloadsAPI, type User } from "@/lib/api"
import { Check, XCircle, X, ArrowUpDown, Square } from "lucide-react"

interface BulkState {
  running: boolean; idx: number; total: number; current: string; detail: string
  fileSection: string; fileCurrent: number; fileTotal: number
  done: { downloaded: number; skipped: number; failed: number; cancelled: boolean } | null
  error: string; cancelling: boolean
}

interface Props {
  allResults: User[]
  isSearching: boolean
  sessionId: string | null
  filters: { pub: boolean; priv: boolean; ver: boolean; kw: string; minFol: number }
  filtered: User[]
  sortCol: string
  setFilter: (key: any, value: any) => void
  toggleSort: (col: string) => void
  applyFilters: (list: User[]) => User[]
  bulk: BulkState
  downloadStatus: Record<string, string>
  downloadLabel: Record<string, string>
  onExportCsv: () => void
  onDownload: (username: string, pk: number, sections?: string) => void
  onStopDownload: (username: string) => void
  onStartBulk: (users: { username: string; pk: number }[]) => void
  onCancelBulk: () => void
  onClearBulkDone: () => void
}

const DL_TTL_HOURS = 24

function pacingFor(n: number) {
  if (n <= 20) return { delayAvg: 11.5, restEvery: 0,  restAvg: 0 }
  if (n <= 80) return { delayAvg: 22.5, restEvery: 30, restAvg: 67.5 }
  return { delayAvg: 35, restEvery: 25, restAvg: 135 }
}

function estimateBulk(n: number) {
  const p = pacingFor(n)
  let secs = n * (p.delayAvg + 20)
  if (p.restEvery) secs += Math.floor(n / p.restEvery) * p.restAvg
  return secs
}

function fmtDuration(secs: number) {
  const h = Math.floor(secs / 3600)
  const m = Math.round((secs % 3600) / 60)
  if (h && m) return `~${h}h ${m}min`
  if (h) return `~${h}h`
  return `~${m} min`
}

export default function ResultsCard({
  allResults, isSearching, sessionId, filters, filtered, sortCol, setFilter, toggleSort, applyFilters,
  bulk, downloadStatus, downloadLabel,
  onExportCsv, onDownload, onStopDownload,
  onStartBulk, onCancelBulk, onClearBulkDone,
}: Props) {
  const [downloadedMap, setDownloadedMap] = useState<Record<string, any>>({})

  useEffect(() => { loadDownloaded() }, [])
  useEffect(() => { if (bulk.done) loadDownloaded() }, [bulk.done])

  const doneKeys = useMemo(
    () => Object.entries(downloadStatus).filter(([, s]) => s === "ok" || s === "error").map(([u]) => u).join(","),
    [downloadStatus],
  )
  useEffect(() => { if (doneKeys) loadDownloaded() }, [doneKeys])

  async function loadDownloaded() {
    const { res, data } = await fetchDownloadsAPI()
    if (res.ok) setDownloadedMap(data.users || {})
  }

  function dlInfo(username: string) {
    const e = downloadedMap[username]
    if (!e?.downloaded_at) return null
    const when = new Date(e.downloaded_at)
    const ageH = (Date.now() - when.getTime()) / 3.6e6
    return { when, ageH, fresh: ageH < DL_TTL_HOURS, gallery: e.gallery, stories: e.stories, highlights: e.highlights || 0 }
  }

  function relTime(ageH: number) {
    if (ageH < 1) return "recién"
    if (ageH < 24) return `hace ${Math.round(ageH)}h`
    const d = Math.round(ageH / 24)
    return d === 1 ? "ayer" : `hace ${d}d`
  }

  const downloadedCount = useMemo(
    () => allResults.reduce((n, u) => n + (dlInfo(u.username) ? 1 : 0), 0),
    [allResults, downloadedMap],
  )

  function downloadAllGalleries() {
    if (bulk.running) return
    const users = allResults.map(u => ({ username: u.username, pk: u.pk }))
    if (!users.length) return
    const eta = fmtDuration(estimateBulk(users.length))
    if (!confirm(
      `Voy a recorrer ${users.length} usuarios y bajar las galerías + historias nuevas.\n` +
      `Incluye historias activas y destacadas.\n` +
      `Salteo a quien ya se bajó hace menos de 1 día.\n\n` +
      `Tiempo estimado: ${eta} (aprox).\n` +
      `Corre en segundo plano: podés cerrar la pestaña y volver.\n¿Continuar?`
    )) return
    onStartBulk(users)
  }

  function proxyUrl(url: string) {
    return url ? `${API_BASE}/api/proxy-image?url=${encodeURIComponent(url)}` : ""
  }

  const resultsTitle = useMemo(() => {
    const { pub, priv, ver, kw, minFol } = filters
    const active = [
      pub    && "públicos",
      priv   && "privados",
      ver    && "verificados",
      minFol > 0 && `≥${minFol.toLocaleString()} seg.`,
      kw     && `"${kw}"`,
    ].filter(Boolean)
    const suffix = active.length ? ` · ${active.join(", ")}` : ""
    return `${filtered.length} de ${allResults.length}${suffix}`
  }, [filters, filtered.length, allResults.length])

  function btnLabel(username: string) {
    const s = downloadStatus[username]
    if (s === "downloading") return downloadLabel[username] || "..."
    if (s === "ok") return <><Check size={14} /> {downloadLabel[username]}</>
    if (s === "error") return <><XCircle size={14} /> {downloadLabel[username]}</>
    return "Descargar"
  }

  return (
    <div className="card card-wide results-card">
      <div className="results-header">
        <div className="flex items-center gap-2">
          <h2>{resultsTitle}</h2>
        </div>
        <div className="flex gap-2 items-center">
          {downloadedCount > 0 && (
            <span className="font-mono text-[0.72rem] text-dim bg-field border border-edge-soft rounded-field px-[0.45rem] py-[0.2rem] whitespace-nowrap"
              title="Usuarios de este listado con galería ya descargada">
              {downloadedCount}/{allResults.length} bajados
            </span>
          )}
          {sessionId && (
            <button className="btn-secondary btn-sm" disabled={bulk.running} onClick={downloadAllGalleries}
              title="Baja la galería + historias de todos los resultados (saltea los de hace menos de 1 día)">
              {bulk.running ? "Descargando…" : "Descargar galerías"}
            </button>
          )}
          <button className="btn-secondary btn-sm" onClick={onExportCsv}>Exportar CSV</button>
        </div>
      </div>

      {(bulk.running || bulk.done || bulk.error) && (
        <div className="mt-[0.6rem] mb-[0.4rem] px-[0.7rem] py-[0.55rem] bg-field border border-edge-soft rounded-field">
          {bulk.running && (
            <>
              <div className="flex items-center gap-[0.55rem] text-[0.82rem] flex-wrap">
                <span className="num font-semibold text-accent tabular-nums">{bulk.idx}/{bulk.total}</span>
                {bulk.current && <span className="user-link font-semibold">@{bulk.current}</span>}
                {bulk.fileTotal > 0 && bulk.fileCurrent > 0
                  ? <span className="font-mono text-[0.76rem] text-ink">
                      {bulk.fileSection === "gallery" ? "Galería" : "Historias"} {bulk.fileCurrent}/{bulk.fileTotal}
                    </span>
                  : bulk.detail && <span className="font-mono text-[0.76rem] text-dim">{bulk.detail}</span>
                }
                <button className="btn-icon ml-auto" disabled={bulk.cancelling} onClick={onCancelBulk}
                  aria-label="Cancelar descarga masiva"
                  title={bulk.cancelling ? "Cancelando…" : "Cancelar (guarda lo ya bajado)"}><X size={14} /></button>
              </div>
              {/* Barra de usuarios */}
              <div className="mt-[0.45rem] h-1 bg-surface-2 rounded-sm overflow-hidden">
                <div className="h-full bg-accent transition-[width] duration-300"
                  style={{ width: bulk.total ? `${bulk.idx / bulk.total * 100}%` : "0%" }} />
              </div>
              {/* Barra de archivos del usuario actual */}
              <div className="mt-[0.25rem] h-[3px] bg-surface-2 rounded-sm overflow-hidden">
                <div className="h-full bg-accent/50 transition-[width] duration-150"
                  style={{ width: bulk.fileTotal ? `${bulk.fileCurrent / bulk.fileTotal * 100}%` : "0%" }} />
              </div>
            </>
          )}
          {!bulk.running && bulk.error && (
            <div className="flex items-center gap-[0.55rem] text-[0.82rem] flex-wrap text-danger"><XCircle size={14} /> {bulk.error}</div>
          )}
          {!bulk.running && bulk.done && (
            <div className="flex items-center gap-[0.55rem] text-[0.82rem] flex-wrap">
              {bulk.done.cancelled ? <><Square size={12} /> Cancelado</> : <><Check size={12} /> Listo</>} ·{" "}
              <span className="num">{bulk.done.downloaded}</span> bajados ·{" "}
              <span className="num">{bulk.done.skipped}</span> salteados ·{" "}
              <span className="num">{bulk.done.failed}</span> fallaron
              <button className="btn-icon" onClick={onClearBulkDone} aria-label="Cerrar"><X size={14} /></button>
            </div>
          )}
        </div>
      )}

      <div className="filter-row">
        <label className={`chip${filters.pub ? " on" : ""}`}
          onClick={() => { setFilter("pub", !filters.pub); if (!filters.pub) setFilter("priv", false) }}>
          Solo públicos
        </label>
        <label className={`chip${filters.priv ? " on" : ""}`}
          onClick={() => { setFilter("priv", !filters.priv); if (!filters.priv) setFilter("pub", false) }}>
          Solo privados
        </label>
        <label className={`chip${filters.ver ? " on" : ""}`}
          onClick={() => setFilter("ver", !filters.ver)}>
          Solo verificados
        </label>
        <input className="filter-input" type="text" placeholder="Filtrar por bio..."
          value={filters.kw} onChange={e => setFilter("kw", e.target.value)} />
        <input className="filter-input max-w-[140px]" type="number" placeholder="Mín. seguidores" min={0}
          value={filters.minFol || ""} onChange={e => setFilter("minFol", Number(e.target.value) || 0)} />
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th className="num hidden xs:table-cell">#</th>
              <th>Usuario</th>
              <th className="sort num" onClick={() => toggleSort("follower_count")}>Seguidores <ArrowUpDown size={12} /></th>
              <th className="sort num hidden sm:table-cell" onClick={() => toggleSort("following_count")}>Siguiendo <ArrowUpDown size={12} /></th>
              <th className="sort num hidden sm:table-cell" onClick={() => toggleSort("media_count")}>Posts <ArrowUpDown size={12} /></th>
              <th>Bajada</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={7} className="empty">
                {isSearching
                  ? "Consultando Instagram, esperá…"
                  : allResults.length > 0
                    ? "Sin resultados con los filtros activos."
                    : ""}
              </td></tr>
            )}
            {filtered.map((u, i) => {
              const dl = dlInfo(u.username)
              return (
                <tr key={u.username}>
                  <td className="num hidden xs:table-cell">{i + 1}</td>
                  <td>
                    <div className="flex items-center gap-2">
                      {u.profile_pic_url_hd && (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={proxyUrl(u.profile_pic_url_hd)} alt="" className="w-7 h-7 rounded-full object-cover shrink-0 bg-field hidden xxs:block" loading="lazy" onError={e => { (e.currentTarget as HTMLImageElement).style.display = "none" }} />
                      )}
                      <div className="min-w-0">
                        <a href={`https://instagram.com/${u.username}`} target="_blank" rel="noreferrer" className="user-link">
                          @{u.username}
                        </a>
                        {u.full_name && <div className="text-dim text-[0.75rem] truncate">{u.full_name}</div>}
                      </div>
                    </div>
                  </td>
                  <td className="num">{u.follower_count.toLocaleString()}</td>
                  <td className="num hidden sm:table-cell">{u.following_count.toLocaleString()}</td>
                  <td className="num hidden sm:table-cell">{u.media_count.toLocaleString()}</td>
                  <td>
                    {dl ? (
                      <span className={`font-mono text-[0.72rem] whitespace-nowrap ${dl.fresh ? "text-accent" : "text-private"}`}
                        title={`Galería: ${dl.gallery} · Historias: ${dl.stories} · Destacadas: ${dl.highlights} · ${dl.when.toLocaleString("es")}`}>
                        <Check size={12} /> {relTime(dl.ageH)}
                      </span>
                    ) : (
                      <span className="font-mono text-[0.72rem] whitespace-nowrap text-faint">—</span>
                    )}
                  </td>
                  <td>
                    <div className="flex flex-col gap-1 py-[0.4rem] whitespace-nowrap sm:flex-row sm:gap-[0.35rem]">
                      {sessionId && (downloadStatus[u.username] === "downloading" ? (
                        <div className="flex items-center gap-[0.3rem]">
                          <span className="font-mono text-accent whitespace-nowrap overflow-hidden text-ellipsis max-w-[70px] text-[0.65rem] sm:max-w-[110px] sm:text-[0.72rem]"
                            title={downloadLabel[u.username]}>{downloadLabel[u.username]}</span>
                          <button className="btn-icon" onClick={() => onStopDownload(u.username)}
                            aria-label="Detener descarga"><X size={12} /></button>
                        </div>
                      ) : downloadStatus[u.username] === "ok" || downloadStatus[u.username] === "error" ? (
                        <span className={`font-mono whitespace-nowrap overflow-hidden text-ellipsis max-w-[140px] sm:max-w-[200px] text-[0.65rem] sm:text-[0.72rem] inline-flex items-center gap-1 ${downloadStatus[u.username] === "ok" ? "text-accent" : "text-danger"}`}
                          title={downloadLabel[u.username]}>
                          {downloadStatus[u.username] === "ok" ? <Check size={12} /> : <XCircle size={12} />}
                          {downloadLabel[u.username]}
                        </span>
                      ) : (
                        <>
                          <button className="btn-posts w-full sm:w-auto"
                            onClick={() => onDownload(u.username, u.pk)}>
                            {btnLabel(u.username)}
                          </button>
                          <button className="btn-posts w-full sm:w-auto"
                            onClick={() => onDownload(u.username, u.pk, "stories")}
                            title="Solo historias activas (no galería)">Stories</button>
                          <button className="btn-posts w-full sm:w-auto"
                            onClick={() => onDownload(u.username, u.pk, "highlights")}
                            title="Solo historias destacadas">Destacadas</button>
                        </>
                      ))}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
