"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** Proporción de un Short: 9 de ancho por 16 de alto. */
const VERTICAL_RATIO = 9 / 16;

interface Props {
  /** Dimensiones reales del vídeo, para trabajar en sus píxeles. */
  sourceWidth: number;
  sourceHeight: number;
  /** Posición actual del recorte, en píxeles del original. */
  cropX: number | null;
  /** Si la posición la ha fijado una persona o la ha decidido la máquina. */
  manual: boolean;
  onChange: (cropX: number) => void;
  onReset: () => void;
}

/**
 * Rectángulo 9:16 arrastrable sobre el reproductor.
 *
 * Hasta ahora el encuadre se decidía en el servidor y no se veía hasta abrir el
 * MP4 terminado: si el automático se equivocaba, la única salida era volver a
 * generar el clip y mirar otra vez. Con esto se ve **antes** qué parte del
 * fotograma sobrevive, y se corrige arrastrando.
 *
 * Se dibuja en porcentajes sobre el contenedor del vídeo en lugar de en
 * píxeles: el reproductor cambia de tamaño con la ventana, y las coordenadas
 * que importan son las del vídeo original, no las de la pantalla.
 */
export function CropOverlay({
  sourceWidth,
  sourceHeight,
  cropX,
  manual,
  onChange,
  onReset,
}: Props) {
  const frameRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);

  // Ancho de la ventana vertical dentro del original. Con una fuente 16:9 sale
  // algo menos de un tercio del ancho: por eso centrar se deja tanto fuera.
  const windowWidth = Math.min(sourceWidth, Math.round(sourceHeight * VERTICAL_RATIO));
  const maximum = Math.max(0, sourceWidth - windowWidth);
  const current = cropX ?? Math.round(maximum / 2);

  const moveTo = useCallback(
    (clientX: number) => {
      const box = frameRef.current?.getBoundingClientRect();
      if (!box || box.width === 0) return;
      const ratio = (clientX - box.left) / box.width;
      // El puntero marca el CENTRO de la ventana: arrastrar por la esquina
      // superior izquierda es contraintuitivo cuando lo que se coloca es un
      // encuadre.
      const centred = ratio * sourceWidth - windowWidth / 2;
      onChange(Math.max(0, Math.min(maximum, Math.round(centred))));
    },
    [maximum, onChange, sourceWidth, windowWidth],
  );

  // Los listeners van en `window` y no en el elemento: si el puntero se sale
  // del vídeo a media faena, el arrastre debe seguir hasta que se suelte.
  useEffect(() => {
    if (!dragging) return;
    const onMove = (event: PointerEvent) => moveTo(event.clientX);
    const onUp = () => setDragging(false);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, [dragging, moveTo]);

  if (sourceWidth <= 0 || sourceHeight <= 0 || maximum <= 0) return null;

  const leftPercent = (current / sourceWidth) * 100;
  const widthPercent = (windowWidth / sourceWidth) * 100;

  return (
    <div
      ref={frameRef}
      className="pointer-events-auto absolute inset-0 cursor-ew-resize touch-none"
      onPointerDown={(event) => {
        event.preventDefault();
        setDragging(true);
        moveTo(event.clientX);
      }}
    >
      {/* Lo que se pierde, atenuado. Es la forma más directa de enseñar que
          un recorte vertical se come dos tercios de un plano 16:9. */}
      <div
        className="absolute inset-y-0 left-0 bg-black/55"
        style={{ width: `${leftPercent}%` }}
      />
      <div
        className="absolute inset-y-0 right-0 bg-black/55"
        style={{ width: `${100 - leftPercent - widthPercent}%` }}
      />

      <div
        className={`absolute inset-y-0 border-2 ${
          manual ? "border-violet-400" : "border-emerald-400/80"
        }`}
        style={{ left: `${leftPercent}%`, width: `${widthPercent}%` }}
      >
        <span
          className={`absolute left-1/2 top-2 -translate-x-1/2 rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${
            manual ? "bg-violet-400 text-violet-950" : "bg-emerald-400 text-emerald-950"
          }`}
        >
          {manual ? "encuadre tuyo" : "encuadre automático"}
        </span>

        {/* Asideros: no hacen nada por sí solos, pero dicen que esto se
            arrastra sin tener que explicarlo. */}
        <span className="absolute inset-y-0 left-0 my-auto h-10 w-1 -translate-x-1/2 self-center rounded bg-white/70" />
        <span className="absolute inset-y-0 right-0 my-auto h-10 w-1 translate-x-1/2 self-center rounded bg-white/70" />
      </div>

      {manual && (
        <button
          type="button"
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => {
            event.stopPropagation();
            onReset();
          }}
          className="absolute bottom-2 right-2 rounded-lg bg-black/70 px-2.5 py-1 text-[11px] text-zinc-200 transition hover:bg-black/90 hover:text-white"
        >
          Volver al automático
        </button>
      )}
    </div>
  );
}
