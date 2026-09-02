import { API_BASE_URL } from "@/lib/config";
import type { Page, ProjectDetail, ProjectSummary, Readiness } from "@/lib/types";

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
 * Readiness: estado de Postgres, Redis y el worker Celery.
 *
 * Devuelve 503 cuando alguna dependencia falla, pero el cuerpo sigue siendo
 * util (dice CUAL falla), asi que lo aceptamos en lugar de lanzar.
 */
export function getReadiness(): Promise<Readiness> {
  return apiFetch<Readiness>("/health/ready", { acceptStatuses: [503] });
}

/** Crea un proyecto y encola su procesamiento. */
export function createProject(url: string): Promise<ProjectDetail> {
  return apiFetch<ProjectDetail>("/api/projects", {
    method: "POST",
    body: JSON.stringify({ url }),
  });
}

/** Reprocesa un proyecto terminado o fallido. */
export function retryProject(id: string): Promise<ProjectDetail> {
  return apiFetch<ProjectDetail>(`/api/projects/${id}/retry`, { method: "POST" });
}

export function listProjects(limit = 20, offset = 0): Promise<Page<ProjectSummary>> {
  return apiFetch<Page<ProjectSummary>>(`/api/projects?limit=${limit}&offset=${offset}`);
}
