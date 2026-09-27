// Formato compartido del resumen persistente de una descarga (evento SSE "done"
// de /api/download-user/stream). Usado por DownloadsCard y page.tsx para mostrar
// siempre el mismo formato, p.ej.:
//   +3 galería · historias 2 activas (+2) · +0 destacadas
// con errores de sección resaltados aparte.

export interface DownloadFound {
  gallery: number | null
  stories: number | null
  highlights: number | null
}

export interface DownloadSectionErrors {
  gallery: string | null
  stories: string | null
  highlights: string | null
}

export interface DownloadDoneEvent {
  type: "done"
  gallery: number
  stories: number
  highlights: number
  new_gallery: number
  new_stories: number
  new_highlights: number
  found?: DownloadFound | null
  section_errors?: DownloadSectionErrors | null
}

export interface SummarySegment {
  text: string
  danger: boolean
}

/** Nombre visible de una sección de progreso ("gallery" | "stories" | "highlights"). */
export function sectionLabel(section: string): string {
  return section === "gallery" ? "Galería" : section === "highlights" ? "Destacadas" : "Historias"
}

/** Arma los segmentos del resumen persistente por sección, en el orden
 * galería → historias → destacadas. Solo incluye las secciones que se
 * pidieron en la descarga (found[sección] !== null/undefined). */
const EMPTY_FOUND: DownloadFound = { gallery: null, stories: null, highlights: null }
const EMPTY_ERRORS: DownloadSectionErrors = { gallery: null, stories: null, highlights: null }

export function formatDownloadSummary(ev: DownloadDoneEvent): SummarySegment[] {
  const found = ev.found || EMPTY_FOUND
  const errors = ev.section_errors || EMPTY_ERRORS
  const segments: SummarySegment[] = []

  if (errors.gallery) {
    segments.push({ text: `Galería: error — ${errors.gallery}`, danger: true })
  } else if (found.gallery !== null && found.gallery !== undefined) {
    segments.push({ text: `+${ev.new_gallery} galería`, danger: false })
  }

  if (errors.stories) {
    segments.push({ text: `Historias: error — ${errors.stories}`, danger: true })
  } else if (found.stories !== null && found.stories !== undefined) {
    segments.push({
      text: found.stories === 0
        ? "sin historias activas"
        : `historias ${found.stories} activas (+${ev.new_stories})`,
      danger: false,
    })
  }

  if (errors.highlights) {
    segments.push({ text: `Destacadas: error — ${errors.highlights}`, danger: true })
  } else if (found.highlights !== null && found.highlights !== undefined) {
    segments.push({ text: `+${ev.new_highlights} destacadas`, danger: false })
  }

  if (segments.length === 0) {
    segments.push({ text: "Descargado", danger: false })
  }

  return segments
}
