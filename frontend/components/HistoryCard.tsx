"use client"
import { useState, useEffect } from "react"
import { fetchRunsAPI, fetchRunDetailAPI, fetchDiffAPI, type Run } from "@/lib/api"

const MODO_LABEL: Record<string, string> = { following: "Seguidos", followers: "Seguidores" }

function fmtDate(iso: string) {
  if (!iso) return "—"
  return new Date(iso).toLocaleString("es", { day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit" })
}

function runLabel(r: Run) {
  const t = r.target_username ? `@${r.target_username}` : "(mi cuenta)"
  return `${MODO_LABEL[r.modo] || r.modo} · ${t}`
}

export default function HistoryCard({ sessionId }: { sessionId: string }) {
  const [runs, setRuns]       = useState<Run[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState("")
  const [selected, setSelected] = useState<Run[]>([])
  const [diff, setDiff]         = useState<any>(null)
  const [diffError, setDiffError] = useState("")
  const [detail, setDetail]     = useState<{ run: Run; miembros: any[] | null; loading: boolean } | null>(null)

  useEffect(() => { loadRuns() }, [])

  async function loadRuns() {
    setLoading(true); setError("")
    try {
      const { res, data } = await fetchRunsAPI(sessionId)
      if (!res.ok) throw new Error(data.detail || "Error al cargar el historial")
      setRuns(data.runs || [])
    } catch (e: any) {
      setError(e.message || "No se pudo cargar el historial.")
    } finally {
      setLoading(false)
    }
  }

  function sameGroup(a: Run, b: Run) { return a.modo === b.modo && a.target_username === b.target_username }
  function isSelected(r: Run) { return selected.some(s => s.id === r.id) }
  function selectable(r: Run) {
    if (isSelected(r)) return true
    if (selected.length === 0) return true
    return sameGroup(r, selected[0])
  }

  function toggleSelect(r: Run) {
    setDiff(null); setDiffError("")
    if (isSelected(r)) {
      setSelected(prev => prev.filter(s => s.id !== r.id))
    } else if (!selectable(r)) {
      return
    } else if (selected.length < 2) {
      setSelected(prev => [...prev, r])
    } else {
      setSelected(prev => [prev[1], r])
    }
  }

  const canCompare = selected.length === 2 && sameGroup(selected[0], selected[1])

  async function compare() {
    if (!canCompare) return
    setDiffError("")
    const [a, b] = [...selected].sort((x, y) => new Date(x.created_at).getTime() - new Date(y.created_at).getTime())
    const { res, data } = await fetchDiffAPI(sessionId, a.id, b.id)
    if (res.ok) setDiff({ ...data, base: a, compare: b })
    else setDiffError(data.detail || "No se pudo comparar.")
  }

  async function openDetail(r: Run) {
    setDetail({ run: r, miembros: null, loading: true })
    const { res, data } = await fetchRunDetailAPI(sessionId, r.id)
    setDetail({ run: r, miembros: res.ok ? data.miembros || [] : [], loading: false })
  }

  return (
    <div className="card card-wide">
      <div className="results-header">
        <h2>Historial de análisis</h2>
        <button className="btn-secondary btn-sm" onClick={loadRuns}>Actualizar</button>
      </div>

      {canCompare ? (
        <p className="status-msg mb-3">
          Seleccionadas {selected.length}/2 ·{" "}
          <button className="btn-analizar" onClick={compare}>Comparar unfollowers</button>
        </p>
      ) : (
        <p className="status-msg mb-3">
          Elegí 2 corridas <strong>del mismo tipo y objetivo</strong> para comparar quién apareció y quién se fue.
        </p>
      )}
      {diffError && <p className="error-msg mb-3">{diffError}</p>}

      {diff && (
        <div className="diff-panel">
          <div className="diff-head">
            <span className="user-link">{runLabel(diff.base)}</span>
            <span className="text-faint">{fmtDate(diff.base.created_at)}</span>
            <span className="text-faint">→</span>
            <span className="user-link">{runLabel(diff.compare)}</span>
            <span className="text-faint">{fmtDate(diff.compare.created_at)}</span>
          </div>
          <div className="diff-cols">
            <div>
              <div className="diff-col-title gained">+ {diff.gained_count} nuevos</div>
              {diff.gained.length === 0 && <div className="empty">—</div>}
              {diff.gained.map((u: string) => (
                <a key={u} className="diff-user gained" href={`https://instagram.com/${u}`} target="_blank" rel="noreferrer">@{u}</a>
              ))}
            </div>
            <div>
              <div className="diff-col-title lost">− {diff.lost_count} se fueron</div>
              {diff.lost.length === 0 && <div className="empty">—</div>}
              {diff.lost.map((u: string) => (
                <a key={u} className="diff-user lost" href={`https://instagram.com/${u}`} target="_blank" rel="noreferrer">@{u}</a>
              ))}
            </div>
          </div>
        </div>
      )}

      {loading && <div className="empty">Cargando historial...</div>}
      {!loading && error && <div className="empty text-danger">{error}</div>}
      {!loading && !error && runs.length === 0 && (
        <div className="empty">Todavía no hay corridas guardadas. Hacé un análisis y aparecerá acá.</div>
      )}

      {!loading && runs.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th></th>
                <th className="num">#</th>
                <th className="hidden sm:table-cell">Fecha</th>
                <th className="hidden xxs:table-cell">Análisis</th>
                <th className="num hidden xs:table-cell">Total</th>
                <th className="num hidden xs:table-cell">Caché</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {runs.map(r => (
                <tr key={r.id} className={`${isSelected(r) ? "row-selected" : ""} ${!selectable(r) ? "row-disabled" : ""}`}>
                  <td>
                    <input type="checkbox" checked={isSelected(r)} disabled={!selectable(r)}
                      title={!selectable(r) ? "Distinto tipo u objetivo que la corrida ya elegida" : ""}
                      onChange={() => toggleSelect(r)} />
                  </td>
                  <td className="num">{r.id}</td>
                  <td className="hidden sm:table-cell">{fmtDate(r.created_at)}</td>
                  <td className="hidden xxs:table-cell">{runLabel(r)}</td>
                  <td className="num hidden xs:table-cell">{r.total.toLocaleString()}</td>
                  <td className="num hidden xs:table-cell" title={`${r.from_cache} servidos desde caché`}>{r.from_cache}</td>
                  <td><button className="btn-posts" onClick={() => openDetail(r)}>Ver</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {detail && (
        <div className="detail-panel">
          <div className="results-header">
            <h2>{runLabel(detail.run)} · {fmtDate(detail.run.created_at)}</h2>
            <button className="btn-secondary btn-sm" onClick={() => setDetail(null)}>Cerrar</button>
          </div>
          {detail.loading && <div className="empty">Cargando...</div>}
          {!detail.loading && detail.miembros?.length === 0 && <div className="empty">Sin miembros.</div>}
          {!detail.loading && detail.miembros && detail.miembros.length > 0 && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th className="num">#</th>
                    <th>Usuario</th>
                    <th className="hidden sm:table-cell">Nombre</th>
                    <th className="num hidden xs:table-cell">Seguidores</th>
                    <th className="num hidden xs:table-cell">Siguiendo</th>
                    <th className="num hidden xs:table-cell">Posts</th>
                    <th>Estado</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.miembros.map((m: any, i: number) => (
                    <tr key={m.username}>
                      <td className="num">{i + 1}</td>
                      <td><a className="user-link" href={`https://instagram.com/${m.username}`} target="_blank" rel="noreferrer">@{m.username}</a></td>
                      <td className="text-dim hidden sm:table-cell">{m.full_name || "—"}</td>
                      <td className="num hidden xs:table-cell">{m.follower_count.toLocaleString()}</td>
                      <td className="num hidden xs:table-cell">{m.following_count.toLocaleString()}</td>
                      <td className="num hidden xs:table-cell">{m.media_count.toLocaleString()}</td>
                      <td>
                        {m.is_verified && <span className="badge badge-v">Verificado</span>}
                        {m.is_private  && <span className="badge badge-p">Privado</span>}
                        {!m.is_verified && !m.is_private && "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
