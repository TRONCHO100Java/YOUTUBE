import { API_BASE_URL } from "@/lib/config";
import type {
  CandidateStatus,
  ClipCandidate,
  GeneratedClip,
  Page,
  ProjectDetail,
  ProjectSummary,
  Readiness,
  SignalTimeline,
  TaskRef,
  TaskState,
  PublishChannel,
  RoutedClip,
  VideoResult,
  WatchedChannel,
  BatchResult,
} from "@/lib/types";

/** Error con la forma que devuelve el manejador central de la API. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string = "unknown",
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface ApiErrorBody {
  error?: { code?: string; message?: string };
}

interface FetchOptions extends RequestInit {
  /** Codigos que NO son error y cuyo cuerpo queremos leer igualmente. */
  acceptStatuses?: readonly number[];
}

async function apiFetch<T>(path: string, options: FetchOptions = {}): Promise<T> {
  const { acceptStatuses = [], ...init } = options;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init.headers },
      cache: "no-store",
    });
  } catch {
    // fetch solo rechaza por fallo de red: API caida, CORS o DNS.
    throw new ApiError(`No se puede conectar con la API en ${API_BASE_URL}`, 0, "network_error");
  }

  if (!response.ok && !acceptStatuses.includes(response.status)) {
    const body = (await response.json().catch(() => ({}))) as ApiErrorBody;
    throw new ApiError(
      body.error?.message ?? `La API respondió ${response.status}`,
      response.status,
      body.error?.code ?? "http_error",
    );
  }

  return (await response.json()) as T;
}

/**
 * Variante para respuestas sin cuerpo (204).
 *
 * `apiFetch` siempre intenta parsear JSON, y un DELETE que responde 204 no
 * trae ninguno: parsearlo lanzaría un error de sintaxis sobre una respuesta
 * que en realidad ha ido bien.
 */
async function apiFetchVoid(path: string, options: FetchOptions = {}): Promise<void> {
  const { acceptStatuses = [], ...init } = options;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init.headers },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(`No se puede conectar con la API en ${API_BASE_URL}`, 0, "network_error");
  }

  if (!response.ok && !acceptStatuses.includes(response.status)) {
    const body = (await response.json().catch(() => ({}))) as ApiErrorBody;
    throw new ApiError(
      body.error?.message ?? `La API respondió ${response.status}`,
      response.status,
      body.error?.code ?? "http_error",
    );
  }
}

/**
 * Readiness: estado de Postgres, Redis y el worker Celery.
 *
 * Devuelve 503 cuando alguna dependencia falla, pero el cuerpo sigue siendo
 * util (dice CUAL falla), asi que lo aceptamos en lugar de lanzar.
 */
export function getReadiness(): Promise<Readiness> {
  return apiFetch<Readiness>("/health/ready", { acceptStatuses: [503] });
}

/** Crea un proyecto y encola su procesamiento. */
export function createProject(url: string, keywords?: string): Promise<ProjectDetail> {
  return apiFetch<ProjectDetail>("/api/projects", {
    method: "POST",
    body: JSON.stringify({ url, keywords: keywords?.trim() || null }),
  });
}

/**
 * Cambia las palabras clave de un proyecto ya creado.
 *
 * No relanza nada: para que surtan efecto hay que regenerar, y esa decisión
 * es del usuario, que sabe si le compensa volver a pasar el vídeo entero.
 */
export function updateProjectKeywords(
  id: string,
  keywords: string,
): Promise<ProjectDetail> {
  return apiFetch<ProjectDetail>(`/api/projects/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ keywords }),
  });
}

/**
 * Reescribe solo los títulos, sin volver a renderizar.
 *
 * El título no está dentro del MP4, así que esto cuesta segundos en vez de
 * todo el pipeline. No toca el gancho, que sí va incrustado en los píxeles.
 */
export function retitleProject(id: string): Promise<TaskRef> {
  return apiFetch<TaskRef>(`/api/projects/${id}/retitle`, { method: "POST" });
}

/** Estado de una tarea encolada. */
export function getTask(taskId: string): Promise<TaskState> {
  return apiFetch<TaskState>(`/api/tasks/${taskId}`);
}

/**
 * Espera a que una tarea termine, preguntando cada poco.
 *
 * Un error de red aislado no se toma como final: el worker puede estar
 * ocupado y la API tardar en responder, y abandonar a la primera dejaría al
 * usuario sin saber si su trabajo se hizo. Lo que sí acaba la espera es el
 * plazo: mejor decir "está tardando" que quedarse girando para siempre.
 */
export async function waitForTask(
  taskId: string,
  { intervalMs = 1500, timeoutMs = 180_000 }: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<TaskState | null> {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
    try {
      const state = await getTask(taskId);
      if (state.ready) return state;
    } catch {
      // Se reintenta en la siguiente vuelta.
    }
  }

  return null;
}

/** Reprocesa un proyecto terminado o fallido. */
export function retryProject(id: string): Promise<ProjectDetail> {
  return apiFetch<ProjectDetail>(`/api/projects/${id}/retry`, { method: "POST" });
}

// ------------------------------------------------------------- ingesta ---

/** Busca vídeos en YouTube. Sin API key: lo resuelve yt-dlp por detrás. */
export function searchVideos(
  query: string,
  filters: { minDuration?: number; maxDuration?: number; minViews?: number } = {},
): Promise<VideoResult[]> {
  const params = new URLSearchParams({ q: query });
  if (filters.minDuration) params.set("min_duration", String(filters.minDuration));
  if (filters.maxDuration) params.set("max_duration", String(filters.maxDuration));
  if (filters.minViews) params.set("min_views", String(filters.minViews));
  return apiFetch<VideoResult[]>(`/api/search?${params}`);
}

/** Encola varias URLs de una vez. Una mala no tumba las demás. */
export function createBatch(urls: string[], keywords?: string): Promise<BatchResult> {
  return apiFetch<BatchResult>("/api/projects/batch", {
    method: "POST",
    body: JSON.stringify({ urls, keywords: keywords?.trim() || null }),
  });
}

/** Canales cuyos vídeos nuevos se procesan solos. */
export function listChannels(): Promise<WatchedChannel[]> {
  return apiFetch<WatchedChannel[]>("/api/channels");
}

export function addChannel(input: {
  channel: string;
  minDuration?: number;
  maxDuration?: number;
  minViews?: number;
  keywords?: string;
  publishChannelId?: string | null;
}): Promise<WatchedChannel> {
  return apiFetch<WatchedChannel>("/api/channels", {
    method: "POST",
    body: JSON.stringify({
      channel: input.channel,
      min_duration: input.minDuration ?? null,
      max_duration: input.maxDuration ?? null,
      min_views: input.minViews ?? null,
      keywords: input.keywords?.trim() || null,
      publish_channel_id: input.publishChannelId || null,
    }),
  });
}

/**
 * `publish_channel_id: null` significa "quítale el destino", no "no lo toques".
 * Por eso se manda solo cuando viene en el parche.
 */
export function updateChannel(
  id: string,
  patch: { enabled?: boolean; keywords?: string; publish_channel_id?: string | null },
): Promise<WatchedChannel> {
  return apiFetch<WatchedChannel>(`/api/channels/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteChannel(id: string): Promise<void> {
  return apiFetchVoid(`/api/channels/${id}`, { method: "DELETE" });
}

/** Revisa un canal ahora, sin esperar al temporizador. */
export function checkChannel(id: string): Promise<TaskRef> {
  return apiFetch<TaskRef>(`/api/channels/${id}/check`, { method: "POST" });
}

// --------------------------------------------- canales de publicacion ---

/** Canales propios donde se publican los clips. */
export function listPublishChannels(): Promise<PublishChannel[]> {
  return apiFetch<PublishChannel[]>("/api/publish-channels");
}

export function createPublishChannel(input: {
  name: string;
  url?: string;
  niche?: string;
  people?: string[];
  topics?: string[];
  kinds?: string[];
  minScore?: number;
  priority?: number;
  notes?: string;
}): Promise<PublishChannel> {
  return apiFetch<PublishChannel>("/api/publish-channels", {
    method: "POST",
    body: JSON.stringify({
      name: input.name,
      url: input.url?.trim() || null,
      niche: input.niche?.trim() || null,
      people: input.people ?? [],
      topics: input.topics ?? [],
      kinds: input.kinds ?? [],
      min_score: input.minScore ?? 0,
      priority: input.priority ?? 0,
      notes: input.notes?.trim() || null,
    }),
  });
}

export function updatePublishChannel(
  id: string,
  patch: {
    enabled?: boolean;
    priority?: number;
    minScore?: number;
    outro_handle?: string;
    outro_tagline?: string;
  },
): Promise<PublishChannel> {
  return apiFetch<PublishChannel>(`/api/publish-channels/${id}`, {
    method: "PATCH",
    body: JSON.stringify({
      enabled: patch.enabled,
      priority: patch.priority,
      min_score: patch.minScore,
      outro_handle: patch.outro_handle,
      outro_tagline: patch.outro_tagline,
    }),
  });
}

export function deletePublishChannel(id: string): Promise<void> {
  return apiFetchVoid(`/api/publish-channels/${id}`, { method: "DELETE" });
}

/** Vista previa del reparto: qué clip va a qué canal. No cambia nada. */
/**
 * Fabrica el vídeo de cierre de un canal con su nombre.
 *
 * Aparte de editar el nombre a propósito: cuesta una recodificación, y
 * quien está escribiendo el nombre puede ir por la mitad.
 */
export function buildChannelOutro(id: string): Promise<PublishChannel> {
  return apiFetch<PublishChannel>(`/api/publish-channels/${id}/outro`, {
    method: "POST",
  });
}

export function listRouting(): Promise<RoutedClip[]> {
  return apiFetch<RoutedClip[]>("/api/publish-channels/routing");
}

/** Momentos detectados por la IA, del mejor al peor. */
export function listCandidates(projectId: string): Promise<ClipCandidate[]> {
  return apiFetch<ClipCandidate[]>(`/api/projects/${projectId}/candidates`);
}

/**
 * Sube el clip a YouTube.
 *
 * Con la privacidad de YOUTUBE_PRIVACY, que es `private` a propósito: la API
 * restringe a privado todo lo que sube un proyecto sin auditar.
 */
export function publishClip(clipId: string): Promise<TaskRef> {
  return apiFetch<TaskRef>(`/api/clips/${clipId}/publish`, { method: "POST" });
}

/**
 * Marca el clip como ya publicado, subido como se haya subido.
 *
 * Sin esto el sistema no se entera de una subida a mano y el clip volvería a
 * la bandeja del canal en cada exportación.
 */
export function markClipUploaded(clipId: string): Promise<GeneratedClip> {
  return apiFetch<GeneratedClip>(`/api/clips/${clipId}/uploaded`, { method: "POST" });
}

/** Borra el MP4 para dejar sitio. La ficha del clip se conserva. */
export function deleteClipFile(clipId: string): Promise<GeneratedClip> {
  return apiFetch<GeneratedClip>(`/api/clips/${clipId}/file`, { method: "DELETE" });
}

/** Clips ya renderizados, del mejor al peor. */
export function listClips(projectId: string): Promise<GeneratedClip[]> {
  return apiFetch<GeneratedClip[]>(`/api/projects/${projectId}/clips`);
}

/** URL del MP4. El navegador la pide directamente, sin pasar por apiFetch. */
export function clipVideoUrl(clipId: string): string {
  return `${API_BASE_URL}/api/clips/${clipId}/video`;
}

/** URL del .srt suelto, para publicar el clip con subtítulos aparte. */
export function clipSubtitlesUrl(clipId: string): string {
  return `${API_BASE_URL}/api/clips/${clipId}/subtitles`;
}

export function listProjects(limit = 20, offset = 0): Promise<Page<ProjectSummary>> {
  return apiFetch<Page<ProjectSummary>>(`/api/projects?limit=${limit}&offset=${offset}`);
}

// ------------------------------------------------------- editor manual ---

/** Detalle de un proyecto: es lo que consulta el polling del editor. */
export function getProject(id: string): Promise<ProjectDetail> {
  return apiFetch<ProjectDetail>(`/api/projects/${id}`);
}

/** Línea de tiempo de señales: energía, cortes, movimiento y bloques. */
export function getSignals(projectId: string): Promise<SignalTimeline> {
  return apiFetch<SignalTimeline>(`/api/projects/${projectId}/signals`);
}

/**
 * URL del vídeo original.
 *
 * La pide directamente la etiqueta `<video>`, que necesita peticiones por
 * rangos para poder saltar dentro de un fichero de cientos de megas.
 */
export function projectSourceUrl(projectId: string): string {
  return `${API_BASE_URL}/api/projects/${projectId}/source`;
}

/** Crea un candidato a partir de un recorte hecho a mano. */
export function createCandidate(
  projectId: string,
  span: { start_time: number; end_time: number; title: string },
): Promise<ClipCandidate> {
  return apiFetch<ClipCandidate>(`/api/projects/${projectId}/candidates`, {
    method: "POST",
    body: JSON.stringify(span),
  });
}

/** Ajusta entrada, salida, título o estado de un candidato. */
export function updateCandidate(
  candidateId: string,
  changes: Partial<{
    start_time: number;
    end_time: number;
    title: string;
    /** Texto que se escribe sobre el vídeo. Cadena vacía lo quita. */
    hook: string;
    /** Recorte 9:16 en píxeles del original. -1 vuelve al automático. */
    crop_x: number;
    status: CandidateStatus;
  }>,
): Promise<ClipCandidate> {
  return apiFetch<ClipCandidate>(`/api/candidates/${candidateId}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

/** Encola el render de un único clip. */
export function renderCandidate(candidateId: string): Promise<ClipCandidate> {
  return apiFetch<ClipCandidate>(`/api/candidates/${candidateId}/render`, {
    method: "POST",
  });
}

/** Borra un candidato y, en cascada, el clip que hubiera generado. */
export async function deleteCandidate(candidateId: string): Promise<void> {
  await apiFetchVoid(`/api/candidates/${candidateId}`, { method: "DELETE" });
}
