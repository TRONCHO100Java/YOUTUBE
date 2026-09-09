"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { CropOverlay } from "@/components/CropOverlay";
import { SignalTimeline } from "@/components/SignalTimeline";
import { createCandidate, projectSourceUrl } from "@/lib/api";
import type {
  ClipCandidate,
  ProjectDetail,
  SignalTimeline as Timeline,
} from "@/lib/types";

/** Velocidades de la lanzadera, como en cualquier editor: J retrocede, L avanza. */
const SHUTTLE_RATES = [1, 2, 4, 8] as const;

/** Salto de las flechas. Con Shift se mueve fotograma a fotograma (aprox.). */
const STEP_SECONDS = 1;
const FINE_STEP_SECONDS = 1 / 25;

interface Props {
  project: ProjectDetail;
  timeline: Timeline | null;
  candidates: ClipCandidate[];
  /** Clip sobre el que se está trabajando; su encuadre es el que se edita. */
  active: ClipCandidate | null;
  onCreated: () => void;
  onCropChange: (candidateId: string, cropX: number) => void;
}

/**
 * Reproductor del vídeo original con marcas de entrada y salida.
 *
 * Existe porque la IA se equivoca, y cuando se equivoca hoy no había nada que
 * hacer salvo reprocesar y cruzar los dedos. Con esto, un vídeo del que el
 * análisis no sacó nada sigue siendo perfectamente aprovechable.
 */
export function ClipEditor({
  project,
  timeline,
  candidates,
  active,
  onCreated,
  onCropChange,
}: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(project.duration ?? 0);
  // Dimensiones reales del fichero: el recuadro de encuadre trabaja en
  // píxeles del original, no en los del reproductor.
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [markIn, setMarkIn] = useState<number | null>(null);
  const [markOut, setMarkOut] = useState<number | null>(null);
  const [title, setTitle] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const seek = useCallback((seconds: number) => {
    const video = videoRef.current;
    if (!video) return;
    const target = Math.min(Math.max(seconds, 0), video.duration || seconds);
    video.currentTime = target;
    setCurrentTime(target);
  }, []);

  const nudge = useCallback(
    (delta: number) => seek((videoRef.current?.currentTime ?? 0) + delta),
    [seek],
  );

  const shuttle = useCallback((direction: -1 | 0 | 1) => {
    const video = videoRef.current;
    if (!video) return;

    if (direction === 0) {
      video.pause();
      return;
    }
    if (direction === 1) {
      // L pulsado varias veces sube la velocidad, como en un editor de verdad.
      const next = SHUTTLE_RATES.find((rate) => rate > video.playbackRate) ?? SHUTTLE_RATES[0];
      video.playbackRate = video.paused ? 1 : next;
      void video.play();
      return;
    }
    // El vídeo HTML no reproduce hacia atrás: J salta hacia atrás a saltos.
    video.pause();
    video.currentTime = Math.max(0, video.currentTime - 2);
  }, []);

  const selectSpan = useCallback(
    (start: number, end: number) => {
      setMarkIn(start);
      setMarkOut(end);
      seek(start);
    },
    [seek],
  );

  // ------------------------------------------------------------- teclado
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      // Sin esto, escribir el título del clip dispararía los atajos.
      const target = event.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;

      const video = videoRef.current;
      if (!video) return;

      switch (event.key.toLowerCase()) {
        case " ":
          event.preventDefault();
          if (video.paused) void video.play();
          else video.pause();
          break;
        case "i":
          event.preventDefault();
          setMarkIn(video.currentTime);
          break;
        case "o":
          event.preventDefault();
          setMarkOut(video.currentTime);
          break;
        case "j":
          event.preventDefault();
          shuttle(-1);
          break;
        case "k":
          event.preventDefault();
          shuttle(0);
          break;
        case "l":
          event.preventDefault();
          shuttle(1);
          break;
        case "arrowleft":
          event.preventDefault();
          nudge(event.shiftKey ? -FINE_STEP_SECONDS : -STEP_SECONDS);
          break;
        case "arrowright":
          event.preventDefault();
          nudge(event.shiftKey ? FINE_STEP_SECONDS : STEP_SECONDS);
          break;
        default:
          break;
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [nudge, shuttle]);

  // -------------------------------------------------------------- guardar
  const span = markIn !== null && markOut !== null ? markOut - markIn : null;
  const canSave = span !== null && span >= 1 && !saving;

  async function save() {
    if (markIn === null || markOut === null) return;
    setSaving(true);
    setError(null);
    try {
      await createCandidate(project.id, {
        start_time: Number(markIn.toFixed(3)),
        end_time: Number(markOut.toFixed(3)),
        title: title.trim() || `Clip en ${formatTime(markIn)}`,
      });
      setTitle("");
      setMarkIn(null);
      setMarkOut(null);
      onCreated();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "No se ha podido crear el clip");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="space-y-3" aria-label="Editor de clips">
      <div className="relative overflow-hidden rounded-xl border border-white/10 bg-black">
        <video
          ref={videoRef}
          src={projectSourceUrl(project.id)}
          controls
          preload="metadata"
          className="mx-auto max-h-[52vh] w-full bg-black"
          onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
          onLoadedMetadata={(event) => {
            setDuration(event.currentTarget.duration);
            setSize({
              width: event.currentTarget.videoWidth,
              height: event.currentTarget.videoHeight,
            });
          }}
          onPause={(event) => {
            // La lanzadera deja la velocidad alterada; al parar se vuelve a 1x
            // para que el siguiente play no salga disparado.
            event.currentTarget.playbackRate = 1;
          }}
        />

        {/* El recuadro solo aparece con un clip seleccionado: sin uno no hay
            encuadre concreto que corregir, y taparía el vídeo para nada. */}
        {active && (
          <CropOverlay
            sourceWidth={size.width}
            sourceHeight={size.height}
            cropX={active.crop_x ?? active.rendered_crop_x}
            manual={active.crop_x !== null}
            onChange={(value) => onCropChange(active.id, value)}
            onReset={() => onCropChange(active.id, -1)}
          />
        )}
      </div>

      {active && (
        <p className="text-xs text-zinc-500">
          Encuadre de <span className="text-zinc-300">{active.title}</span>. Arrastra
          sobre el vídeo para moverlo y vuelve a generar el clip para aplicarlo.
        </p>
      )}

      {timeline ? (
        <SignalTimeline
          timeline={timeline}
          candidates={candidates}
          currentTime={currentTime}
          markIn={markIn}
          markOut={markOut}
          onSeek={seek}
          onSelectSpan={selectSpan}
        />
      ) : (
        <p className="rounded-xl border border-dashed border-white/10 px-4 py-6 text-center text-sm text-zinc-500">
          Este proyecto no tiene señales medidas. Vuelve a procesarlo para generar la
          línea de tiempo de volumen y cortes de plano.
        </p>
      )}

      {/* ------------------------------------------------------ controles */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-white/10 bg-white/[0.03] p-3">
        <div className="flex items-center gap-2">
          <MarkButton
            label="Entrada"
            shortcut="I"
            value={markIn}
            tone="emerald"
            onClick={() => setMarkIn(currentTime)}
            onClear={() => setMarkIn(null)}
          />
          <MarkButton
            label="Salida"
            shortcut="O"
            value={markOut}
            tone="rose"
            onClick={() => setMarkOut(currentTime)}
            onClear={() => setMarkOut(null)}
          />
        </div>

        <span className="font-mono text-sm tabular-nums text-zinc-400">
          {formatTime(currentTime)}
          <span className="text-zinc-600"> / {formatTime(duration)}</span>
        </span>

        {span !== null && (
          <span
            className={`rounded-md px-2 py-1 font-mono text-xs tabular-nums ${durationTone(span)}`}
          >
            {span > 0 ? `${span.toFixed(1)}s` : "rango inválido"}
          </span>
        )}

        <input
          type="text"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="Título del clip (opcional)"
          className="min-w-40 flex-1 rounded-lg border border-white/10 bg-black/40 px-3 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-white/25 focus:outline-none"
        />

        <button
          type="button"
          onClick={() => void save()}
          disabled={!canSave}
          className="rounded-lg bg-emerald-500/90 px-4 py-1.5 text-sm font-medium text-emerald-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-white/10 disabled:text-zinc-500"
        >
          {saving ? "Creando…" : "Crear clip"}
        </button>
      </div>

      {error && (
        <p role="alert" className="text-sm text-rose-400">
          {error}
        </p>
      )}

      <p className="font-mono text-[11px] text-zinc-600">
        espacio reproducir · I entrada · O salida · J K L lanzadera · ← → ±1s ·
        shift+← → fotograma
      </p>
    </section>
  );
}

interface MarkButtonProps {
  label: string;
  shortcut: string;
  value: number | null;
  tone: "emerald" | "rose";
  onClick: () => void;
  onClear: () => void;
}

function MarkButton({ label, shortcut, value, tone, onClick, onClear }: MarkButtonProps) {
  const accent = tone === "emerald" ? "text-emerald-400" : "text-rose-400";
  return (
    <span className="inline-flex items-center overflow-hidden rounded-lg border border-white/10">
      <button
        type="button"
        onClick={onClick}
        className="px-3 py-1.5 text-xs text-zinc-300 transition hover:bg-white/5 hover:text-zinc-100"
        title={`Marcar ${label.toLowerCase()} (${shortcut})`}
      >
        {label}
        <span className="ml-1.5 text-zinc-600">{shortcut}</span>
      </button>
      <span className={`min-w-14 px-2 font-mono text-xs tabular-nums ${accent}`}>
        {value === null ? "—" : formatTime(value)}
      </span>
      {value !== null && (
        <button
          type="button"
          onClick={onClear}
          aria-label={`Quitar marca de ${label.toLowerCase()}`}
          className="px-2 py-1.5 text-xs text-zinc-600 transition hover:bg-white/5 hover:text-zinc-300"
        >
          ×
        </button>
      )}
    </span>
  );
}

/** Verde en la zona cómoda para redes, ámbar fuera de ella. */
function durationTone(seconds: number): string {
  if (seconds < 1) return "bg-rose-500/15 text-rose-300";
  if (seconds >= 10 && seconds <= 90) return "bg-emerald-500/15 text-emerald-300";
  return "bg-amber-500/15 text-amber-300";
}

function formatTime(seconds: number): string {
  const total = Math.max(0, seconds);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${minutes}:${rest < 10 ? "0" : ""}${rest.toFixed(1)}`;
}
