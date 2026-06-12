"use client"
import { useState, useEffect, useMemo } from "react"
import { fetchDownloadsAPI, type User } from "@/lib/api"

interface BulkState {
  running: boolean; idx: number; total: number; current: string; detail: string
  done: { downloaded: number; skipped: number; failed: number; cancelled: boolean } | null
  error: string; cancelling: boolean
}

interface Props {
  allResults: User[]
  sessionId: string | null
  filters: { pub: boolean; priv: boolean; ver: boolean; kw: string; minFol: number }
  filtered: User[]
  sortCol: string
  setFilter: (key: any, value: any) => void
  toggleSort: (col: string) => void
  applyFilters: (list: User[]) => User[]
  resultsStack: { results: User[]; title: string }[]
  bulk: BulkState
  downloadStatus: Record<string, string>
  downloadLabel: Record<string, string>
  onAnalizar: (username: string, pk: number, stackTitle: string) => void
  onGoBack: () => void
  onExportCsv: () => void
  onDownload: (username: string, pk: number) => void
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
  allResults, sessionId, filters, filtered, sortCol, setFilter, toggleSort, applyFilters,
  resultsStack, bulk, downloadStatus, downloadLabel,
  onAnalizar, onGoBack, onExportCsv, onDownload, onStopDownload,
  onStartBulk, onCancelBulk, onClearBulkDone,
}: Props) {
  const [downloadedMap, setDownloadedMap] = useState<Record<string, any>>({})

  useEffect(() => { loadDownloaded() }, [])
  useEffect(() => { if (bulk.done) loadDownloaded() }, [bulk.done])

  async function loadDownloaded() {
    const { res, data } = await fetchDownloadsAPI()
    if (res.ok) setDownloadedMap(data.users || {})
  }

  function dlInfo(username: string) {
    const e = downloadedMap[username]
    if (!e?.downloaded_at) return null
    const when = new Date(e.downloaded_at)
    const ageH = (Date.now() - when.getTime()) / 3.6e6
    return { when, ageH, fresh: ageH < DL_TTL_HOURS, gallery: e.gallery, stories: e.stories }
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
      `Salteo a quien ya se bajó hace menos de 1 día.\n\n` +
      `Tiempo estimado: ${eta} (aprox).\n` +
      `Corre en segundo plano: podés cerrar la pestaña y volver.\n¿Continuar?`
    )) return
    onStartBulk(users)
  }

  function proxyUrl(url: string) {
    return url ? `/api/proxy-image?url=${encodeURIComponent(url)}` : ""
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
    if (s === "ok") return "✓"
    if (s === "error") return "✗"
    return "Descargar"
  }

  return (
    <div className="card card-wide results-card">
      <div className="results-header">
        <div className="flex items-center gap-2">
          {resultsStack.length > 0 && (
            <button className="btn-secondary btn-sm" onClick={onGoBack}>← Volver</button>
          )}
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
                <span className="num font-semibold text-accent">{bulk.idx}/{bulk.total}</span>
                {bulk.current && <span className="user-link">@{bulk.current}</span>}
                <span className="text-dim font-mono text-[0.76rem]">{bulk.detail}</span>
                <button className="btn-icon" disabled={bulk.cancelling} onClick={onCancelBulk}
                  aria-label="Cancelar descarga masiva"
                  title={bulk.cancelling ? "Cancelando…" : "Cancelar (guarda lo ya bajado)"}>×</button>
              </div>
              <div className="mt-[0.45rem] h-1 bg-surface-2 rounded-sm overflow-hidden">
                <div className="h-full bg-accent transition-[width] duration-300"
                  style={{ width: bulk.total ? `${bulk.idx / bulk.total * 100}%` : "0%" }} />
              </div>
            </>
          )}
          {!bulk.running && bulk.error && (
            <div className="flex items-center gap-[0.55rem] text-[0.82rem] flex-wrap text-danger">✗ {bulk.error}</div>
          )}
          {!bulk.running && bulk.done && (
            <div className="flex items-center gap-[0.55rem] text-[0.82rem] flex-wrap">
              {bulk.done.cancelled ? "■ Cancelado" : "✓ Listo"} ·{" "}
              <span className="num">{bulk.done.downloaded}</span> bajados ·{" "}
              <span className="num">{bulk.done.skipped}</span> salteados ·{" "}
              <span className="num">{bulk.done.failed}</span> fallaron
              <button className="btn-icon" onClick={onClearBulkDone} aria-label="Cerrar">×</button>
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
              <th className="hidden sm:table-cell">Nombre</th>
              <th className="sort num" onClick={() => toggleSort("follower_count")}>Seguidores ↕</th>
              <th className="sort num hidden sm:table-cell" onClick={() => toggleSort("following_count")}>Siguiendo ↕</th>
              <th className="sort num hidden sm:table-cell" onClick={() => toggleSort("media_count")}>Posts ↕</th>
              <th className="hidden xs:table-cell">Estado</th>
              <th>Bajada</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr><td colSpan={9} className="empty">
                {allResults.length > 0 ? "Sin resultados con los filtros activos." : ""}
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
                        <img src={proxyUrl(u.profile_pic_url_hd)} alt="" className="w-7 h-7 rounded-full object-cover shrink-0 bg-field hidden xxs:block" loading="lazy" />
                      )}
                      <a href={`https://instagram.com/${u.username}`} target="_blank" rel="noreferrer" className="user-link">
                        @{u.username}
                      </a>
                    </div>
                  </td>
                  <td className="text-dim hidden sm:table-cell">{u.full_name || "—"}</td>
                  <td className="num">{u.follower_count.toLocaleString()}</td>
                  <td className="num hidden sm:table-cell">{u.following_count.toLocaleString()}</td>
                  <td className="num hidden sm:table-cell">{u.media_count.toLocaleString()}</td>
                  <td className="hidden xs:table-cell">
                    {u.is_verified && <span className="badge badge-v">Verificado</span>}
                    {u.is_private  && <span className="badge badge-p">Privado</span>}
                    {!u.is_verified && !u.is_private && "—"}
                  </td>
                  <td>
                    {dl ? (
                      <span className={`font-mono text-[0.72rem] whitespace-nowrap ${dl.fresh ? "text-accent" : "text-private"}`}
                        title={`Galería: ${dl.gallery} · Historias: ${dl.stories} · ${dl.when.toLocaleString("es")}`}>
                        ✓ {relTime(dl.ageH)}
                      </span>
                    ) : (
                      <span className="font-mono text-[0.72rem] whitespace-nowrap text-faint">—</span>
                    )}
                  </td>
                  <td>
                    <div className="flex flex-col gap-1 py-[0.4rem] whitespace-nowrap sm:flex-row sm:gap-[0.35rem]">
                      <button className="btn-analizar w-full sm:w-auto"
                        onClick={() => onAnalizar(u.username, u.pk, resultsTitle)}>Analizar</button>
                      {sessionId && (downloadStatus[u.username] === "downloading" ? (
                        <div className="flex items-center gap-[0.3rem]">
                          <span className="font-mono text-accent whitespace-nowrap overflow-hidden text-ellipsis max-w-[70px] text-[0.65rem] sm:max-w-[110px] sm:text-[0.72rem]"
                            title={downloadLabel[u.username]}>{downloadLabel[u.username]}</span>
                          <button className="btn-icon" onClick={() => onStopDownload(u.username)}
                            aria-label="Detener descarga">×</button>
                        </div>
                      ) : (
                        <button className="btn-posts w-full sm:w-auto"
                          onClick={() => onDownload(u.username, u.pk)}>
                          {btnLabel(u.username)}
                        </button>
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
