"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface PollingState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => void;
}

/**
 * Consulta periódicamente un recurso de la API.
 *
 * Es el mecanismo de actualización del MVP. Cuando incorporemos SSE/WebSockets
 * bastará con sustituir la implementación de este hook: los componentes que lo
 * consumen no cambian.
 */
export function usePolling<T>(fetcher: () => Promise<T>, intervalMs: number): PollingState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Ref para que cambiar `fetcher` en cada render no reinicie el intervalo.
  // Se sincroniza en un efecto: mutar una ref durante el render no es valido.
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  }, [fetcher]);

  const mountedRef = useRef(true);

  const run = useCallback(async () => {
    try {
      const result = await fetcherRef.current();
      if (!mountedRef.current) return;
      setData(result);
      setError(null);
    } catch (cause) {
      if (!mountedRef.current) return;
      setData(null);
      setError(cause instanceof Error ? cause.message : "Error desconocido");
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    // La primera consulta se agenda en lugar de ejecutarse en el cuerpo del
    // efecto: así el efecto solo suscribe a un sistema externo (el temporizador)
    // y nunca provoca un setState sincrono durante el render.
    const immediate = setTimeout(() => void run(), 0);
    const interval = setInterval(() => void run(), intervalMs);
    return () => {
      mountedRef.current = false;
      clearTimeout(immediate);
      clearInterval(interval);
    };
  }, [run, intervalMs]);

  const refresh = useCallback(() => void run(), [run]);

  return { data, error, loading, refresh };
}
