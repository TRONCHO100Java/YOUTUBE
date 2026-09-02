"use client";

import { useEffect, useState } from "react";

import { listCandidates } from "@/lib/api";
import { SCORE_LABELS, type ClipCandidate } from "@/lib/types";

function formatRange(start: number, end: number): string {
  return `${formatTime(start)} – ${formatTime(end)}`;
}

function formatTime(seconds: number): string {
  const total = Math.round(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** Verde para lo bueno, ámbar para lo dudoso: se lee de un vistazo. */
function scoreTone(score: number): string {
  if (score >= 80) return "text-emerald-400";
  if (score >= 60) return "text-amber-400";
  return "text-zinc-400";
}

export function CandidateList({ projectId }: { projectId: string }) {
  const [candidates, setCandidates] = useState<ClipCandidate[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listCandidates(projectId)
      .then((result) => {
        if (!cancelled) setCandidates(result);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : "Error desconocido");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (error) {
    return <p className="px-4 pb-4 text-sm text-rose-400">{error}</p>;
  }

  if (candidates === null) {
    return <p className="px-4 pb-4 text-sm text-zinc-500">Cargando momentos…</p>;
  }

  if (candidates.length === 0) {
    return (
      <p className="px-4 pb-4 text-sm text-zinc-500">
        Este proyecto todavía no tiene momentos detectados.
      </p>
    );
  }

  return (
    <ol className="space-y-2 px-3 pb-3">
      {candidates.map((candidate, index) => (
        <li key={candidate.id} className="rounded-lg border border-white/5 bg-black/20 p-3">
          <div className="flex items-baseline gap-3">
            <span className="text-xs text-zinc-600">#{candidate.rank ?? index + 1}</span>
            <span className={`text-lg font-semibold tabular-nums ${scoreTone(candidate.score)}`}>
              {Math.round(candidate.score)}
              <span className="text-xs font-normal text-zinc-600">/100</span>
            </span>
            <p className="min-w-0 flex-1 truncate text-sm text-zinc-100">{candidate.title}</p>
            <span className="shrink-0 text-xs tabular-nums text-zinc-500">
              {formatRange(candidate.start_time, candidate.end_time)} ·{" "}
              {Math.round(candidate.duration)}s
            </span>
          </div>

          {candidate.hook && (
            <p className="mt-2 border-l-2 border-emerald-500/40 pl-3 text-sm italic text-zinc-300">
              {candidate.hook}
            </p>
          )}

          {candidate.reason && (
            <p className="mt-2 text-xs leading-relaxed text-zinc-500">{candidate.reason}</p>
          )}

          <dl className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
            {SCORE_LABELS.map(([key, label, max]) => (
              <div key={key} className="flex items-baseline gap-1">
                <dt className="text-[11px] text-zinc-600">{label}</dt>
                <dd className="text-[11px] tabular-nums text-zinc-400">
                  {candidate.scores[key] ?? "—"}
                  <span className="text-zinc-700">/{max}</span>
                </dd>
              </div>
            ))}
          </dl>
        </li>
      ))}
    </ol>
  );
}
