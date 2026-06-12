"use client"
import { useState } from "react"

interface Props {
  loggedUser: string
  isSearching: boolean
  progressIdx: number
  progressTotal: number
  progressPct: number
  status: string
  currentTarget: string | null
  onSearch: (modo: string) => void
  onLogout: () => void
  onClearTarget: () => void
}

export default function SearchCard({
  loggedUser, isSearching, progressIdx, progressTotal, progressPct, status,
  currentTarget, onSearch, onLogout, onClearTarget,
}: Props) {
  const [modo, setModo] = useState("following")

  return (
    <div className="w-full max-w-[480px] sm:max-w-[min(600px,90vw)] rounded-card border border-edge-soft bg-surface py-[0.85rem] px-[0.7rem] xs:py-4 xs:px-[0.85rem] sm:py-[1.1rem] sm:px-5">
      <span className="field-label block mb-2">Sesión activa: @{loggedUser}</span>

      {currentTarget && (
        <div className="flex items-center mb-[0.6rem] bg-accent-soft border border-accent rounded-lg gap-[0.35rem] px-[0.55rem] py-[0.3rem] text-[0.75rem] sm:gap-2 sm:px-3 sm:py-[0.35rem] sm:text-[0.82rem]">
          <span className="text-dim shrink-0">Analizando:</span>
          <span className="text-accent font-semibold font-mono">@{currentTarget}</span>
          <button
            className="ml-auto p-1 flex items-center justify-center rounded-full border-0 bg-transparent text-faint leading-none transition-colors hover:bg-surface-2 hover:text-ink w-[1.8rem] h-[1.8rem] text-[0.9rem] sm:w-8 sm:h-8 sm:text-base"
            aria-label="Volver a mi cuenta" onClick={onClearTarget}>×</button>
        </div>
      )}

      <div className="search-actions">
        <div className="toggle flex-1">
          <input type="radio" id="r-following" checked={modo === "following"} onChange={() => setModo("following")} />
          <label htmlFor="r-following">{currentTarget ? "A quienes sigue" : "A quienes sigo"}</label>
          <input type="radio" id="r-followers" checked={modo === "followers"} onChange={() => setModo("followers")} />
          <label htmlFor="r-followers">{currentTarget ? "Sus seguidores" : "Mis seguidores"}</label>
        </div>
        <button
          className="btn-primary w-auto min-h-[44px] flex-1 px-[0.7rem] py-[0.4rem] text-[0.82rem] xs:px-4 xs:py-2 xs:text-[0.87rem] sm:flex-none"
          disabled={isSearching} onClick={() => onSearch(modo)}>Buscar</button>
        <button
          className="btn-secondary w-auto min-h-[44px] flex-1 px-[0.7rem] py-[0.4rem] text-[0.82rem] xs:px-4 xs:py-2 xs:text-[0.87rem] sm:flex-none"
          disabled={isSearching} onClick={onLogout}>Salir</button>
      </div>

      {isSearching && (
        <div className="mt-[0.65rem]">
          <div className="progress-bar-bg">
            <div className="progress-bar-fill" style={{ width: `${progressPct}%` }} />
          </div>
          <div className="progress-meta">
            <span>
              {progressTotal > 0
                ? `${progressIdx.toLocaleString()} / ${progressTotal.toLocaleString()}`
                : "Obteniendo lista..."}
            </span>
            <span className="inline-flex items-center gap-[0.4rem]">
              <span>{progressPct}%</span>
            </span>
          </div>
        </div>
      )}

      <div className="status-msg">{status}</div>
    </div>
  )
}
