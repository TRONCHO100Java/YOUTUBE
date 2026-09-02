/**
 * Configuracion del cliente.
 *
 * `NEXT_PUBLIC_API_URL` se inyecta en build time. Se centraliza aqui para que
 * mover la API a otro host (cloud) sea un cambio de una sola linea.
 */
export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/+$/, "");

/** Intervalo de polling del estado del sistema y de los proyectos, en ms. */
export const POLL_INTERVAL_MS = 5000;
