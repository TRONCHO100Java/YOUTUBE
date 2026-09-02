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
  created_at: string;
  updated_at: string;
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
