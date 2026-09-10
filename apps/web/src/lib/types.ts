/** Tipos espejo de los schemas de la API (`apps/backend/src/clipforge/api/schemas`). */

export type HealthStatus = "ok" | "degraded" | "error";

export type ProjectStatus =
  | "CREATED"
  | "DOWNLOADING"
  | "TRANSCRIBING"
  | "ANALYZING"
  | "GENERATING_CLIPS"
  | "COMPLETED"
  | "NEEDS_REVIEW"
  | "FAILED";

/** Tipo de contenido detectado; decide la rúbrica y las duraciones. */
export type ContentProfile = "TALKING" | "VISUAL";

/** De dónde salió un candidato. */
export type CandidateSource = "AI" | "SIGNAL" | "MANUAL";

export type CandidateStatus =
  | "PENDING"
  | "SELECTED"
  | "REJECTED"
  | "RENDERING"
  | "RENDERED"
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
  /** De qué va el vídeo y quién sale, tal y como lo escribió el usuario. */
  keywords: string | null;
  /** Avance del pipeline entre 0 y 1, derivado del estado. */
  progress: number;
  content_profile: ContentProfile | null;
  /** Fracción del vídeo con habla real. Explica el perfil elegido. */
  speech_ratio: number | null;
  /** Si hay línea de tiempo de señales que pintar en el editor. */
  has_signals: boolean;
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
  status: CandidateStatus;
  source: CandidateSource;
  start_time: number;
  end_time: number;
  start_segment_index: number | null;
  end_segment_index: number | null;
  duration: number;
  title: string;
  /** Los otros títulos que propuso el redactor: cambiar es un clic, no otra llamada. */
  title_variants: string[];
  hook: string | null;
  /** Descripción para la caja de YouTube, sin el crédito al canal. */
  description: string | null;
  /** Etiquetas sin almohadilla; la primera es siempre "shorts". */
  hashtags: string[];
  reason: string | null;
  transcript_excerpt: string | null;
  error_message: string | null;
  score: number;
  /** null cuando no lo ha juzgado ningún modelo (señales o manual). */
  scores: ClipScoreBreakdown | null;
  clip_id: string | null;
  /** Encuadre corregido a mano. null = manda el automático. */
  crop_x: number | null;
  /** Encuadre con el que se generó el fichero que hay ahora. */
  rendered_crop_x: number | null;
  rendered_crop_width: number | null;
}

export interface GeneratedClip {
  id: string;
  candidate_id: string;
  project_id: string;
  title: string;
  hook: string | null;
  /** Descripción para la caja de YouTube, sin el crédito al canal. */
  description: string | null;
  /** Etiquetas sin almohadilla; la primera es siempre "shorts". */
  hashtags: string[];
  reason: string | null;
  score: number;
  rank: number | null;
  start_time: number;
  end_time: number;
  duration: number | null;
  width: number | null;
  height: number | null;
  filesize_bytes: number | null;
  has_burned_subtitles: boolean;
  has_subtitle_file: boolean;
  encoder: string | null;
  /** Id en YouTube si ya se subió. null = todavía no ha salido de aquí. */
  youtube_video_id: string | null;
  published_at: string | null;
  /** Cuándo se borró el fichero para dejar sitio. La ficha sigue aquí. */
  deleted_at: string | null;
  /** Con qué privacidad quedó: un proyecto de API sin auditar sube en privado. */
  privacy_status: string | null;
  /** Rendimiento real. Lo único que puede decir si la nota acertó. */
  view_count: number | null;
  like_count: number | null;
}

// ------------------------------------------------------------ ingesta ---

/** Un vídeo encontrado en YouTube, sin descargar nada todavía. */
export interface VideoResult {
  video_id: string;
  title: string;
  url: string;
  channel: string | null;
  duration: number | null;
  view_count: number | null;
  thumbnail: string | null;
  published_at: string | null;
  /** Ya hay un proyecto para esta URL: encolarlo otra vez costaría una descarga. */
  already_queued: boolean;
}

/** Qué ha pasado con cada URL de una tanda. */
export interface BatchResult {
  queued: string[];
  duplicated: string[];
  rejected: Record<string, string>;
}

/** Un canal cuyos vídeos nuevos entran solos en la cola. */
export interface WatchedChannel {
  id: string;
  channel_id: string;
  title: string;
  url: string;
  enabled: boolean;
  min_duration: number | null;
  max_duration: number | null;
  min_views: number | null;
  keywords: string | null;
  /** A qué canal propio van los clips de este. */
  publish_channel_id: string | null;
  last_video_published_at: string | null;
  last_checked_at: string | null;
  /** Por qué falló la última revisión: un canal callado y uno roto se ven igual sin esto. */
  last_error: string | null;
  projects_created: number;
  created_at: string;
}

// ------------------------------------------------- canales de publicacion ---

/**
 * Un canal propio al que se suben clips.
 *
 * No confundir con `WatchedChannel`, que es de donde SALEN los vídeos. Este es
 * el otro extremo: dónde acaban los clips ya hechos.
 */
export interface PublishChannel {
  id: string;
  name: string;
  /** null mientras el canal no exista todavía en YouTube. */
  url: string | null;
  enabled: boolean;
  youtube_channel_id: string | null;
  /** Qué acepta este canal. Vacío = cualquiera. */
  niche: string | null;
  people: string[];
  topics: string[];
  kinds: string[];
  /** Puede ser más exigente que el sistema. */
  min_score: number;
  /** A igualdad de encaje, gana el más alto. */
  priority: number;
  notes: string | null;
  created_at: string;
}

/** Un clip listo para subir y el canal que le toca. */
export interface RoutedClip {
  clip_id: string;
  candidate_id: string;
  project_title: string | null;
  title: string;
  description: string | null;
  hashtags: string[];
  score: number;
  duration: number | null;
  tags: Record<string, unknown> | null;
  /** null = no encaja en ninguno; lo reparte una persona. */
  channel_id: string | null;
  channel_name: string | null;
  youtube_video_id: string | null;
}

/** Lo que devuelve un endpoint que encola trabajo. */
export interface TaskRef {
  task_id: string;
  state: string;
}

/**
 * Estado de una tarea encolada.
 *
 * `PENDING` es ambiguo en Celery —"encolada" y "no la conozco" son el mismo
 * estado— y por eso lo que se mira es `ready`, no el nombre del estado.
 */
export interface TaskState {
  task_id: string;
  state: string;
  ready: boolean;
  successful: boolean | null;
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

// ---------------------------------------------------------------- señales ---

/** Punto de una curva continua: `t` en segundos, `v` el valor medido. */
export interface SamplePoint {
  t: number;
  v: number;
}

/** Máximo local de volumen: un golpe, una risa, un remate musical. */
export interface EnergyPeak {
  t: number;
  db: number;
  /** Cuánto sobresale del fondo, 0..1. */
  p: number;
}

/** Tramo candidato derivado solo de señales, sin que ninguna IA lo juzgue. */
export interface MomentBlock {
  start: number;
  end: number;
  energy: number;
  motion: number;
  peaks: number;
  cut_rate: number;
  score: number;
}

export interface SignalTimeline {
  version: number;
  duration: number;
  energy: SamplePoint[];
  peaks: EnergyPeak[];
  cuts: number[];
  motion: SamplePoint[];
  blocks: MomentBlock[];
}

// ------------------------------------------------------------- etiquetas ---

/**
 * ¿El pipeline está trabajando en este proyecto ahora mismo?
 *
 * `CREATED` no cuenta: el proyecto está encolado y puede quedarse ahí un buen
 * rato, porque el worker procesa un vídeo cada vez. Distinguirlo importa —es
 * la diferencia entre "espera" y "actúa"— y lo miran tanto la tarjeta del
 * proyecto como la lista, para saber si hay alguien delante en la cola.
 */
export function isProjectRunning(status: ProjectStatus): boolean {
  return (
    status !== "CREATED" &&
    status !== "COMPLETED" &&
    status !== "NEEDS_REVIEW" &&
    status !== "FAILED"
  );
}

/** Etiquetas en castellano para cada estado del pipeline. */
export const PROJECT_STATUS_LABELS: Record<ProjectStatus, string> = {
  CREATED: "En cola",
  DOWNLOADING: "Descargando vídeo",
  TRANSCRIBING: "Transcribiendo",
  ANALYZING: "Buscando mejores momentos",
  GENERATING_CLIPS: "Generando clips",
  COMPLETED: "Finalizado",
  NEEDS_REVIEW: "Pendiente de revisar",
  FAILED: "Error",
};

export const CANDIDATE_STATUS_LABELS: Record<CandidateStatus, string> = {
  PENDING: "Sin generar",
  SELECTED: "En cola",
  REJECTED: "Descartado",
  RENDERING: "Generando",
  RENDERED: "Listo",
  FAILED: "Error",
};

export const CANDIDATE_SOURCE_LABELS: Record<CandidateSource, string> = {
  AI: "IA",
  SIGNAL: "Señal",
  MANUAL: "Manual",
};

/**
 * Etiquetas de cada dimensión de la puntuación, con su máximo.
 *
 * Las columnas de la base de datos son siempre las mismas siete, pero lo que
 * guardan depende del perfil: en un vídeo visual la columna `curiosity` no mide
 * curiosidad sino la fuerza del remate. Etiquetarlas con el nombre equivocado
 * haría que el desglose no se pudiera leer.
 */
export const SCORE_LABELS: Record<
  ContentProfile,
  Array<[keyof ClipScoreBreakdown, string, number]>
> = {
  TALKING: [
    ["hook", "Gancho", 20],
    ["curiosity", "Curiosidad", 20],
    ["emotion", "Emoción", 15],
    ["clarity", "Claridad", 15],
    ["value", "Valor", 15],
    ["shareability", "Compartir", 10],
    ["duration", "Duración", 5],
  ],
  VISUAL: [
    ["hook", "Premisa", 20],
    ["curiosity", "Remate", 25],
    ["emotion", "Reacción", 15],
    ["clarity", "Universal", 15],
    ["value", "Ritmo", 15],
    ["duration", "Duración", 10],
  ],
};
