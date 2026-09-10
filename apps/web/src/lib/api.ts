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
export function retitleProject(id: string): Promise<ProjectDetail> {
  return apiFetch<ProjectDetail>(`/api/projects/${id}/retitle`, { method: "POST" });
}

/** Reprocesa un proyecto terminado o fallido. */
export function retryProject(id: string): Promise<ProjectDetail> {
  return apiFetch<ProjectDetail>(`/api/projects/${id}/retry`, { method: "POST" });
}

/** Momentos detectados por la IA, del mejor al peor. */
export function listCandidates(projectId: string): Promise<ClipCandidate[]> {
  return apiFetch<ClipCandidate[]>(`/api/projects/${projectId}/candidates`);
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
