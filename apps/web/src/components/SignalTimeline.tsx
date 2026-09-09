"use client";

import { useCallback, useMemo, useRef } from "react";

import type { ClipCandidate, SignalTimeline as Timeline } from "@/lib/types";

/** Alturas de cada carril, en píxeles del sistema de coordenadas del SVG. */
const LANE = {
  energy: { y: 0, height: 46 },
  motion: { y: 50, height: 20 },
  cuts: { y: 74, height: 10 },
  blocks: { y: 88, height: 16 },
  candidates: { y: 108, height: 18 },
} as const;

const TOTAL_HEIGHT = 132;
const VIEW_WIDTH = 1000;

interface Props {
  timeline: Timeline;
  candidates: ClipCandidate[];
  /** Posición actual del reproductor, en segundos. */
  currentTime: number;
  /** Marcas de entrada y salida en curso, si las hay. */
  markIn: number | null;
  markOut: number | null;
  /** Llevar la cabeza lectora a un instante. */
  onSeek: (seconds: number) => void;
  /** Ajustar la selección a un tramo entero de un clic. */
  onSelectSpan: (start: number, end: number) => void;
}

/**
 * Línea de tiempo de cinco carriles sobre el mismo eje.
 *
 * Es lo que convierte el editor manual en algo utilizable: sobre un vídeo sin
 * diálogo, encontrar los gags a ojo son diez minutos de arrastrar la cabeza
 * lectora; con los picos de sonido y los cortes de plano dibujados, es un clic.
 *
 * Se dibuja con SVG y no en canvas a propósito: son unos cientos de elementos,
 * cada uno puede recibir foco y `title`, y así los tramos son navegables con el
 * teclado sin tener que reimplementar la accesibilidad a mano.
 */
export function SignalTimeline({
  timeline,
  candidates,
  currentTime,
  markIn,
  markOut,
  onSeek,
  onSelectSpan,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const duration = timeline.duration || 1;

  const toX = useCallback((seconds: number) => (seconds / duration) * VIEW_WIDTH, [duration]);

  /** Convierte un clic en el SVG al segundo del vídeo que representa. */
  const timeFromEvent = useCallback(
    (clientX: number): number => {
      const box = svgRef.current?.getBoundingClientRect();
      if (!box || box.width === 0) return 0;
      const ratio = Math.min(Math.max((clientX - box.left) / box.width, 0), 1);
      return ratio * duration;
    },
    [duration],
  );

  // Las curvas se convierten en polígonos una sola vez: recalcularlas en cada
  // fotograma del reproductor tiraría el rendimiento por la borda.
  const energyPath = useMemo(
    () => buildAreaPath(timeline.energy, duration, LANE.energy.y, LANE.energy.height),
    [timeline.energy, duration],
  );
  const motionPath = useMemo(
    () => buildAreaPath(timeline.motion, duration, LANE.motion.y, LANE.motion.height),
    [timeline.motion, duration],
  );

  const ticks = useMemo(() => buildTicks(duration), [duration]);

  return (
    <div className="rounded-xl border border-white/10 bg-black/30 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-zinc-500">
        <Legend color="bg-amber-400/80" label="Volumen" />
        <Legend color="bg-sky-400/70" label="Movimiento" />
        <Legend color="bg-zinc-500" label="Cortes de plano" />
        <Legend color="bg-emerald-500/70" label="Tramos propuestos" />
        <Legend color="bg-violet-400/70" label="Clips" />
        <span className="ml-auto text-zinc-600">
          Clic para saltar · clic en un tramo para seleccionarlo
        </span>
      </div>

      <svg
        ref={svgRef}
        viewBox={`0 0 ${VIEW_WIDTH} ${TOTAL_HEIGHT}`}
        preserveAspectRatio="none"
        className="h-36 w-full cursor-crosshair touch-none select-none"
        role="img"
        aria-label="Línea de tiempo de señales del vídeo"
        onClick={(event) => onSeek(timeFromEvent(event.clientX))}
      >
        {/* --- volumen ------------------------------------------------ */}
        <rect
          x={0}
          y={LANE.energy.y}
          width={VIEW_WIDTH}
          height={LANE.energy.height}
          className="fill-white/[0.03]"
        />
        {energyPath && <path d={energyPath} className="fill-amber-400/70" />}

        {/* Picos de volumen: lo que más se parece a "aquí pasa algo". */}
        {timeline.peaks.map((peak) => (
          <line
            key={`peak-${peak.t}`}
            x1={toX(peak.t)}
            x2={toX(peak.t)}
            y1={LANE.energy.y}
            y2={LANE.energy.y + LANE.energy.height}
            className="stroke-amber-200"
            strokeWidth={1.5}
            opacity={0.35 + peak.p * 0.65}
          >
            <title>{`Pico de sonido en ${formatTime(peak.t)} (${peak.db.toFixed(1)} dB)`}</title>
          </line>
        ))}

        {/* --- movimiento --------------------------------------------- */}
        <rect
          x={0}
          y={LANE.motion.y}
          width={VIEW_WIDTH}
          height={LANE.motion.height}
          className="fill-white/[0.03]"
        />
        {motionPath && <path d={motionPath} className="fill-sky-400/60" />}

        {/* --- cortes de plano ---------------------------------------- */}
        {timeline.cuts.map((cut) => (
          <line
            key={`cut-${cut}`}
            x1={toX(cut)}
            x2={toX(cut)}
            y1={LANE.cuts.y}
            y2={LANE.cuts.y + LANE.cuts.height}
            className="stroke-zinc-500"
            strokeWidth={1}
          >
            <title>{`Corte de plano en ${formatTime(cut)}`}</title>
          </line>
        ))}

        {/* --- tramos propuestos por las señales ----------------------- */}
        {timeline.blocks.map((block) => (
          <rect
            key={`block-${block.start}`}
            x={toX(block.start)}
            y={LANE.blocks.y}
            width={Math.max(1, toX(block.end) - toX(block.start))}
            height={LANE.blocks.height}
            rx={2}
            className="cursor-pointer fill-emerald-500/40 hover:fill-emerald-400/70"
            onClick={(event) => {
              // Sin esto, el clic llega también al SVG y solo mueve la cabeza
              // lectora en lugar de seleccionar el tramo.
              event.stopPropagation();
              onSelectSpan(block.start, block.end);
            }}
          >
            <title>
              {`${formatTime(block.start)} – ${formatTime(block.end)} · ` +
                `${Math.round(block.end - block.start)}s · ` +
                `${block.peaks} picos · puntuación ${Math.round(block.score)}`}
            </title>
          </rect>
        ))}

        {/* --- clips ya definidos -------------------------------------- */}
        {candidates.map((candidate) => (
          <rect
            key={`cand-${candidate.id}`}
            x={toX(candidate.start_time)}
            y={LANE.candidates.y}
            width={Math.max(2, toX(candidate.end_time) - toX(candidate.start_time))}
            height={LANE.candidates.height}
            rx={2}
            className={
              candidate.source === "MANUAL"
                ? "cursor-pointer fill-violet-400/70 hover:fill-violet-300"
                : "cursor-pointer fill-violet-400/35 hover:fill-violet-300/70"
            }
            onClick={(event) => {
              event.stopPropagation();
              onSelectSpan(candidate.start_time, candidate.end_time);
            }}
          >
            <title>
              {`${candidate.title} · ${formatTime(candidate.start_time)} – ` +
                `${formatTime(candidate.end_time)}`}
            </title>
          </rect>
        ))}

        {/* --- selección en curso -------------------------------------- */}
        {markIn !== null && markOut !== null && markOut > markIn && (
          <rect
            x={toX(markIn)}
            y={0}
            width={Math.max(1, toX(markOut) - toX(markIn))}
            height={TOTAL_HEIGHT}
            className="pointer-events-none fill-emerald-400/15"
          />
        )}
        {markIn !== null && <Marker x={toX(markIn)} className="stroke-emerald-400" />}
        {markOut !== null && <Marker x={toX(markOut)} className="stroke-rose-400" />}

        {/* --- cabeza lectora ------------------------------------------ */}
        <line
          x1={toX(currentTime)}
          x2={toX(currentTime)}
          y1={0}
          y2={TOTAL_HEIGHT}
          className="pointer-events-none stroke-white"
          strokeWidth={1.5}
        />
      </svg>

      {/* Las marcas de tiempo van en HTML y no en el SVG: `preserveAspectRatio`
          está desactivado para que las curvas ocupen todo el ancho, y eso
          deformaría cualquier texto dibujado dentro. */}
      <div className="relative mt-1 h-4">
        {ticks.map((tick) => (
          <span
            key={tick}
            className="absolute -translate-x-1/2 font-mono text-[10px] text-zinc-600"
            style={{ left: `${(tick / duration) * 100}%` }}
          >
            {formatTime(tick)}
          </span>
        ))}
      </div>
    </div>
  );
}

function Marker({ x, className }: { x: number; className: string }) {
  return (
    <line
      x1={x}
      x2={x}
      y1={0}
      y2={TOTAL_HEIGHT}
      className={`pointer-events-none ${className}`}
      strokeWidth={2}
      strokeDasharray="4 3"
    />
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`inline-block h-2 w-3 rounded-sm ${color}`} aria-hidden="true" />
      {label}
    </span>
  );
}

/**
 * Convierte una serie de muestras en el contorno de un área rellena.
 *
 * Se normaliza contra el propio vídeo: una curva de decibelios va de -90 a 0 y
 * dibujarla en su rango absoluto la dejaría pegada al techo del carril, sin
 * relieve donde se ve lo que importa.
 */
function buildAreaPath(
  points: Array<{ t: number; v: number }>,
  duration: number,
  top: number,
  height: number,
): string | null {
  if (points.length < 2) return null;

  const values = points.map((point) => point.v);
  const low = Math.min(...values);
  const high = Math.max(...values);
  const span = high - low || 1;

  const coords = points.map((point) => {
    const x = (point.t / duration) * VIEW_WIDTH;
    const y = top + height - ((point.v - low) / span) * height;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });

  // `points` tiene al menos dos elementos (comprobado arriba), pero el
  // compilador no puede saberlo con `noUncheckedIndexedAccess`.
  const firstPoint = points.at(0);
  const lastPoint = points.at(-1);
  if (!firstPoint || !lastPoint) return null;

  const first = (firstPoint.t / duration) * VIEW_WIDTH;
  const last = (lastPoint.t / duration) * VIEW_WIDTH;
  const base = top + height;

  return `M${first.toFixed(2)},${base} L${coords.join(" L")} L${last.toFixed(2)},${base} Z`;
}

/** Marcas de tiempo repartidas, con un intervalo redondo según la duración. */
function buildTicks(duration: number): number[] {
  const candidates = [10, 30, 60, 120, 300, 600, 1800];
  const step = candidates.find((value) => duration / value <= 12) ?? 3600;

  const ticks: number[] = [];
  for (let t = 0; t < duration; t += step) ticks.push(t);
  return ticks;
}

function formatTime(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(total / 60);
  return `${minutes}:${String(total % 60).padStart(2, "0")}`;
}
