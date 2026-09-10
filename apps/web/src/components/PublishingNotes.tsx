"use client";

import { CopyButton } from "@/components/CopyButton";

interface Props {
  title: string;
  description: string | null;
  hashtags: string[];
}

/**
 * Lo que hay que pegar en YouTube al subir el clip.
 *
 * Está aquí, junto al clip, porque el momento de subirlo es el momento de
 * mirarlo: tener que abrir la carpeta de exportación a buscar un `.txt` para
 * copiar la descripción es exactamente la fricción que el `.txt` venía a
 * quitar.
 *
 * No lleva el crédito al canal original, que sí llevan los ficheros exportados.
 * Ese lo compone el backend, que conoce la URL de origen; aquí solo tenemos el
 * clip.
 */
export function PublishingNotes({ title, description, hashtags }: Props) {
  if (!description && hashtags.length === 0) return null;

  const tags = hashtags.map((tag) => `#${tag}`).join(" ");
  const clipboard = [title, description, tags].filter(Boolean).join("\n\n");

  return (
    <div className="mt-2 rounded-lg border border-white/5 bg-black/20 p-2.5">
      {description && <p className="text-xs leading-relaxed text-zinc-400">{description}</p>}

      {hashtags.length > 0 && (
        <p className="mt-1.5 text-xs text-sky-400/80">{tags}</p>
      )}

      <div className="mt-2">
        <CopyButton
          value={clipboard}
          label="Copiar para YouTube"
          className="rounded-md border border-white/10 px-2 py-0.5 text-[11px] text-zinc-400 transition hover:border-white/25 hover:text-zinc-100"
        />
      </div>
    </div>
  );
}
