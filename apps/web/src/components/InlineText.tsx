"use client";

import { useState } from "react";

interface Props {
  value: string | null;
  /** Qué se muestra cuando está vacío; hacer clic ahí empieza a escribir. */
  placeholder: string;
  /** Devuelve el valor nuevo ya recortado. Cadena vacía = borrar. */
  onSave: (value: string) => void | Promise<void>;
  className?: string;
  emptyClassName?: string;
  title?: string;
  /** Permite guardar vacío para quitar el texto. */
  allowEmpty?: boolean;
}

/**
 * Texto que se edita haciendo clic encima.
 *
 * Se usa para el título y para el gancho de un clip. Un formulario con su botón
 * de guardar sería más ceremonia de la que merece cambiar cuatro palabras, y en
 * el editor se cambian muchas veces seguidas.
 */
export function InlineText({
  value,
  placeholder,
  onSave,
  className = "",
  emptyClassName = "",
  title,
  allowEmpty = false,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value ?? "");

  function commit() {
    setEditing(false);
    const trimmed = draft.trim();
    if (trimmed === (value ?? "")) return;
    if (!trimmed && !allowEmpty) {
      setDraft(value ?? "");
      return;
    }
    void onSave(trimmed);
  }

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
          if (event.key === "Escape") {
            setDraft(value ?? "");
            setEditing(false);
          }
        }}
        className="min-w-40 flex-1 rounded border border-white/20 bg-black/40 px-2 py-0.5 text-sm text-zinc-100 focus:outline-none"
      />
    );
  }

  return (
    <button
      type="button"
      title={title}
      onClick={() => {
        setDraft(value ?? "");
        setEditing(true);
      }}
      className={`text-left ${value ? className : emptyClassName}`}
    >
      {value || placeholder}
    </button>
  );
}
