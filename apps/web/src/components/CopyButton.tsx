"use client";

import { useEffect, useState } from "react";

interface Props {
  /** Texto que se copia al portapapeles. */
  value: string;
  /** Etiqueta en reposo. Al copiar se sustituye por la confirmación. */
  label?: string;
  className?: string;
}

/** Cuánto dura el "Copiado": lo justo para verlo sin que se quede clavado. */
const FEEDBACK_MS = 1500;

/**
 * Botón que copia un texto y lo confirma en el propio botón.
 *
 * La confirmación va aquí y no en un aviso aparte porque copiar es una acción
 * sin resultado visible: sin este cambio de etiqueta no hay forma de saber si
 * ha funcionado, y se acaba pulsando dos veces.
 *
 * El portapapeles puede fallar —contexto no seguro, permiso denegado— y
 * entonces lo dice, en lugar de fingir que se ha copiado algo que no está.
 */
export function CopyButton({ value, label = "Copiar", className }: Props) {
  const [state, setState] = useState<"idle" | "done" | "failed">("idle");

  useEffect(() => {
    if (state === "idle") return;
    const timer = setTimeout(() => setState("idle"), FEEDBACK_MS);
    return () => clearTimeout(timer);
  }, [state]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setState("done");
    } catch {
      setState("failed");
    }
  }

  return (
    <button
      type="button"
      onClick={() => void copy()}
      className={
        className ??
        "rounded-lg border border-white/10 px-3 py-1 text-xs text-zinc-300 transition hover:border-white/25 hover:text-zinc-100"
      }
    >
      {state === "done" ? "Copiado" : state === "failed" ? "No se ha podido" : label}
    </button>
  );
}
