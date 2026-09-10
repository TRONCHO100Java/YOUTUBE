"use client";

import { useState, type ReactNode } from "react";

interface Props {
  title: string;
  /** Qué es esto, en una línea. Se lee al abrirlo, no antes. */
  hint?: string;
  /** Número o etiqueta corta al lado del título: cuántos hay, si hay aviso. */
  badge?: ReactNode;
  /** Abierto de entrada. La configuración va cerrada; el trabajo, abierto. */
  defaultOpen?: boolean;
  children: ReactNode;
}

/**
 * Una sección que se pliega.
 *
 * Existe porque esta pantalla ya tiene seis bloques —buscar, canales
 * vigilados, canales de destino, proyectos— y todos abiertos a la vez obligan
 * a recorrer media página de formularios para llegar a lo que se usa cada día.
 *
 * Es estado local y no recordado: qué tienes abierto depende de lo que estés
 * haciendo ahora mismo, y guardarlo entre visitas acabaría enseñándote la
 * disposición de un día que ya no te sirve.
 */
export function Collapsible({ title, hint, badge, defaultOpen = false, children }: Props) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <section aria-label={title} className="mt-6 border-t border-white/5 pt-5">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="group flex w-full items-center gap-2 text-left"
      >
        <span
          aria-hidden
          className={`text-xs text-zinc-600 transition-transform ${open ? "rotate-90" : ""}`}
        >
          ▶
        </span>
        <span className="text-sm font-medium text-zinc-400 transition group-hover:text-zinc-200">
          {title}
        </span>
        {badge}
      </button>

      {open && (
        <div className="mt-3">
          {hint && <p className="mb-3 text-xs text-zinc-500">{hint}</p>}
          {children}
        </div>
      )}
    </section>
  );
}
