/** Tipos espejo de los schemas de la API (`apps/backend/src/clipforge/api/schemas`). */

export type HealthStatus = "ok" | "degraded" | "error";

export type ProjectStatus =
  | "CREATED"
  | "DOWNLOADING"
  | "TRANSCRIBING"
  | "ANALYZING"
  | "GENERATING_CLIPS"
  | "COMPLETED"
  | "FAILED";

export interface ComponentHealth {
  status: HealthStatus;
  detail: string | null;
}

export interface Readiness {
  status: HealthStatus;
  app: string;
  version: string;
  environment: string;
  components: Record<string, ComponentHealth>;
}

export interface ProjectSummary {
  id: string;
  source_url: string | null;
  source_type: "YOUTUBE" | "UPLOAD";
  status: ProjectStatus;
  title: string | null;
  duration: number | null;
  thumbnail_url: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectDetail extends ProjectSummary {
  author: string | null;
  /** Avance del pipeline entre 0 y 1, derivado del estado. */
  progress: number;
}

export interface ClipScoreBreakdown {
  hook: number | null;
  curiosity: number | null;
  emotion: number | null;
  clarity: number | null;
  value: number | null;
  shareability: number | null;
  duration: number | null;
}

export interface ClipCandidate {
  id: string;
  project_id: string;
  rank: number | null;
  start_time: number;
  end_time: number;
  duration: number;
  title: string;
  hook: string | null;
  reason: string | null;
  score: number;
  scores: ClipScoreBreakdown;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

/** Etiquetas en castellano para cada estado del pipeline. */
export const PROJECT_STATUS_LABELS: Record<ProjectStatus, string> = {
  CREATED: "Creado",
  DOWNLOADING: "Descargando vídeo",
  TRANSCRIBING: "Transcribiendo",
  ANALYZING: "Buscando mejores momentos",
  GENERATING_CLIPS: "Generando clips",
  COMPLETED: "Finalizado",
  FAILED: "Error",
};

/** Etiquetas de cada dimensión de la puntuación, con su máximo. */
export const SCORE_LABELS: Array<[keyof ClipScoreBreakdown, string, number]> = [
  ["hook", "Gancho", 20],
  ["curiosity", "Curiosidad", 20],
  ["emotion", "Emoción", 15],
  ["clarity", "Claridad", 15],
  ["value", "Valor", 15],
  ["shareability", "Compartir", 10],
  ["duration", "Duración", 5],
];
