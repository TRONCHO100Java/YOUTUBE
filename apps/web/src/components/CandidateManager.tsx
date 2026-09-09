"use client";

import { useState } from "react";

import { InlineText } from "@/components/InlineText";
import {
  clipSubtitlesUrl,
  clipVideoUrl,
  deleteCandidate,
  renderCandidate,
  updateCandidate,
} from "@/lib/api";
import {
  CANDIDATE_SOURCE_LABELS,
  CANDIDATE_STATUS_LABELS,
  SCORE_LABELS,
  type CandidateSource,
  type CandidateStatus,
  type ClipCandidate,
  type ContentProfile,
} from "@/lib/types";

interface Props {
  candidates: ClipCandidate[];
  profile: ContentProfile;
  onChanged: () => void;
  /** Llevar el reproductor al tramo del candidato. */
  onPreview: (start: number, end: number) => void;
}

/**
 * Lista de clips del proyecto, sean de la IA o recortados a mano.
 *
 * Un candidato y un clip renderizado son la misma fila a propósito: para el
 * usuario, "el clip 3" es una sola cosa que a veces todavía no tiene vídeo, y
 * separarlos en dos listas obligaba a cruzarlas mentalmente.
 */
export function CandidateManager({ candidates, profile, onChanged, onPreview }: Props) {
  if (candidates.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-white/10 px-4 py-8 text-center text-sm text-zinc-500">
        Todavía no hay clips. Marca entrada y salida sobre la línea de tiempo y pulsa
        «Crear clip».
      </p>
    );
  }

  return (
    <ol className="space-y-2">
      {candidates.map((candidate) => (
        <CandidateRow
          key={candidate.id}
          candidate={candidate}
          profile={profile}
          onChanged={onChanged}
          onPreview={onPreview}
        />
      ))}
    </ol>
  );
}

function CandidateRow({
  candidate,
  profile,
  onChanged,
  onPreview,
}: {
  candidate: ClipCandidate;
  profile: ContentProfile;
  onChanged: () => void;
  onPreview: (start: number, end: number) => void;
}) {
  const [busy, setBusy] = useState<null | "render" | "delete" | "title" | "hook">(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  async function run(
    kind: "render" | "delete" | "title" | "hook",
    action: () => Promise<unknown>,
  ) {
    setBusy(kind);
    setError(null);
    try {
      await action();
      onChanged();
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "Ha fallado la operación");
    } finally {
      setBusy(null);
    }
  }

  const rendered = candidate.status === "RENDERED" && candidate.clip_id !== null;
  const working = candidate.status === "RENDERING" || candidate.status === "SELECTED";

  return (
    <li className="rounded-xl border border-white/10 bg-white/[0.03] p-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="font-mono text-xs text-zinc-600">#{candidate.rank ?? "—"}</span>

        <SourceBadge source={candidate.source} />

        {candidate.score > 0 && (
          <span className={`font-mono text-sm font-semibold ${scoreTone(candidate.score)}`}>
            {Math.round(candidate.score)}
            <span className="text-xs font-normal text-zinc-600">/100</span>
          </span>
        )}

        <InlineText
          value={candidate.title}
          placeholder="Sin título"
          title="Editar el título del clip"
          className="min-w-0 flex-1 truncate text-sm text-zinc-100 hover:text-white"
          emptyClassName="min-w-0 flex-1 truncate text-sm text-zinc-500 hover:text-zinc-300"
          onSave={(value) => run("title", () => updateCandidate(candidate.id, { title: value }))}
        />

        <button
          type="button"
          onClick={() => onPreview(candidate.start_time, candidate.end_time)}
          className="shrink-0 font-mono text-xs tabular-nums text-zinc-500 underline-offset-2 hover:text-zinc-300 hover:underline"
          title="Ver este tramo en el reproductor"
        >
          {formatTime(candidate.start_time)} – {formatTime(candidate.end_time)} ·{" "}
          {Math.round(candidate.duration)}s
        </button>

        <StatusBadge status={candidate.status} />
      </div>

      {/* El gancho no es decorativo: se escribe SOBRE el vídeo en los primeros
          segundos, y en un clip sin diálogo es lo único escrito que lleva. */}
      <div className="mt-2 flex items-baseline gap-2 border-l-2 border-emerald-500/40 pl-3">
        <span
          className="shrink-0 text-[10px] uppercase tracking-wide text-zinc-600"
          title="Se escribe sobre el vídeo durante los primeros segundos"
        >
          En pantalla
        </span>
        <InlineText
          value={candidate.hook}
          placeholder="+ escribir gancho"
          allowEmpty
          title="Texto que aparece sobre el vídeo. Vacío para quitarlo."
          className="min-w-0 flex-1 text-sm italic text-zinc-300 hover:text-zinc-100"
          emptyClassName="min-w-0 flex-1 text-sm text-zinc-600 hover:text-zinc-400"
          onSave={(value) => run("hook", () => updateCandidate(candidate.id, { hook: value }))}
        />
      </div>

      {candidate.reason && (
        <p className="mt-2 text-xs leading-relaxed text-zinc-500">{candidate.reason}</p>
      )}

      {candidate.scores && (
        <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
          {SCORE_LABELS[profile].map(([key, label, max]) => (
            <div key={key} className="flex items-baseline gap-1">
              <dt className="text-[11px] text-zinc-600">{label}</dt>
              <dd className="text-[11px] tabular-nums text-zinc-400">
                {candidate.scores?.[key] ?? "—"}
                <span className="text-zinc-700">/{max}</span>
              </dd>
            </div>
          ))}
        </dl>
      )}

      {candidate.error_message && (
        <p className="mt-2 text-xs text-rose-400">{candidate.error_message}</p>
      )}
      {error && <p className="mt-2 text-xs text-rose-400">{error}</p>}

      {/* ------------------------------------------------------- acciones */}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={busy !== null || working}
          onClick={() => void run("render", () => renderCandidate(candidate.id))}
          className="rounded-lg border border-white/10 px-3 py-1 text-xs text-zinc-300 transition hover:border-white/25 hover:text-zinc-100 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy === "render" ? "Encolando…" : rendered ? "Regenerar" : "Generar clip"}
        </button>

        {rendered && candidate.clip_id && (
          <>
            <a
              href={clipVideoUrl(candidate.clip_id)}
              target="_blank"
              rel="noreferrer"
              className="rounded-lg border border-white/10 px-3 py-1 text-xs text-zinc-300 transition hover:border-white/25 hover:text-zinc-100"
            >
              Ver
            </a>
            <a
              href={clipVideoUrl(candidate.clip_id)}
              download
              className="rounded-lg border border-white/10 px-3 py-1 text-xs text-zinc-300 transition hover:border-white/25 hover:text-zinc-100"
            >
              Descargar
            </a>
            <a
              href={clipSubtitlesUrl(candidate.clip_id)}
              download
              className="rounded-lg border border-white/10 px-3 py-1 text-xs text-zinc-500 transition hover:border-white/25 hover:text-zinc-300"
            >
              .srt
            </a>
          </>
        )}

        <button
          type="button"
          disabled={busy !== null}
          onClick={() => {
            // Un segundo clic confirma: borrar se lleva también el MP4 ya
            // generado, y sacar un diálogo del navegador por delante es peor.
            if (!confirmingDelete) {
              setConfirmingDelete(true);
              return;
            }
            void run("delete", () => deleteCandidate(candidate.id));
          }}
          onBlur={() => setConfirmingDelete(false)}
          className={`ml-auto rounded-lg border px-3 py-1 text-xs transition disabled:opacity-40 ${
            confirmingDelete
              ? "border-rose-500/50 bg-rose-500/10 text-rose-300"
              : "border-white/10 text-zinc-500 hover:border-rose-500/40 hover:text-rose-300"
          }`}
        >
          {busy === "delete" ? "Borrando…" : confirmingDelete ? "¿Seguro?" : "Borrar"}
        </button>
      </div>
    </li>
  );
}

const SOURCE_TONE: Record<CandidateSource, string> = {
  AI: "border-sky-500/30 bg-sky-500/10 text-sky-300",
  SIGNAL: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  MANUAL: "border-violet-500/30 bg-violet-500/10 text-violet-300",
};

function SourceBadge({ source }: { source: CandidateSource }) {
  return (
    <span
      className={`rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${SOURCE_TONE[source]}`}
      title={
        source === "SIGNAL"
          ? "Detectado por volumen y cortes de plano; nadie lo ha valorado todavía"
          : source === "MANUAL"
            ? "Recortado a mano"
            : "Propuesto por la IA"
      }
    >
      {CANDIDATE_SOURCE_LABELS[source]}
    </span>
  );
}

const STATUS_TONE: Record<CandidateStatus, string> = {
  PENDING: "text-zinc-500",
  SELECTED: "text-sky-400",
  REJECTED: "text-zinc-600",
  RENDERING: "text-amber-400",
  RENDERED: "text-emerald-400",
  FAILED: "text-rose-400",
};

function StatusBadge({ status }: { status: CandidateStatus }) {
  const animate = status === "RENDERING" || status === "SELECTED";
  return (
    <span className={`shrink-0 text-xs ${STATUS_TONE[status]}`}>
      {CANDIDATE_STATUS_LABELS[status]}
      {animate && "…"}
    </span>
  );
}

function scoreTone(score: number): string {
  if (score >= 80) return "text-emerald-400";
  if (score >= 60) return "text-amber-400";
  return "text-zinc-400";
}

function formatTime(seconds: number): string {
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
