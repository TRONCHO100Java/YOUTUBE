"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { CandidateManager } from "@/components/CandidateManager";
import { ClipEditor } from "@/components/ClipEditor";
import { getProject, getSignals, listCandidates } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import { POLL_INTERVAL_MS } from "@/lib/config";
import {
  PROJECT_STATUS_LABELS,
  type ClipCandidate,
  type ProjectDetail,
  type SignalTimeline,
} from "@/lib/types";

/**
 * Página de trabajo de un proyecto: reproductor, señales y lista de clips.
 *
 * El detalle y los candidatos se refrescan por polling porque el render ocurre
 * en el worker; las señales no, porque pesan cientos de kilobytes y solo
 * cambian cuando se reprocesa el proyecto entero.
 */
export function ProjectWorkspace({ projectId }: { projectId: string }) {
  const projectFetcher = useCallback(() => getProject(projectId), [projectId]);
  const { data: project, error } = usePolling<ProjectDetail>(
    projectFetcher,
    POLL_INTERVAL_MS,
  );

  const candidatesFetcher = useCallback(() => listCandidates(projectId), [projectId]);
  const { data: candidates, refresh: refreshCandidates } = usePolling<ClipCandidate[]>(
    candidatesFetcher,
    POLL_INTERVAL_MS,
  );

  const [timeline, setTimeline] = useState<SignalTimeline | null>(null);
  const editorRef = useRef<HTMLDivElement>(null);

  // Las señales se piden una sola vez, en cuanto el proyecto dice que existen.
  const hasSignals = project?.has_signals ?? false;
  useEffect(() => {
    if (!hasSignals || timeline !== null) return;
    let cancelled = false;
    getSignals(projectId)
      .then((result) => {
        if (!cancelled) setTimeline(result);
      })
      .catch(() => {
        // Que no haya señales degrada el editor pero no lo rompe: el
        // reproductor y las marcas siguen funcionando sin la línea de tiempo.
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, hasSignals, timeline]);

  const preview = useCallback((start: number) => {
    const video = editorRef.current?.querySelector("video");
    if (!video) return;
    video.currentTime = start;
    video.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  if (error) {
    return (
      <p role="alert" className="text-sm text-rose-400">
        {error}
      </p>
    );
  }

  if (!project) {
    return <p className="text-sm text-zinc-500">Cargando proyecto…</p>;
  }

  const downloaded = project.status !== "CREATED" && project.status !== "DOWNLOADING";
  const list = candidates ?? [];

  return (
    <div className="space-y-6">
      <header>
        <Link
          href="/"
          className="text-xs text-zinc-500 underline-offset-2 transition hover:text-zinc-300 hover:underline"
        >
          ← Todos los proyectos
        </Link>

        <h1 className="mt-3 text-2xl font-semibold tracking-tight text-zinc-50">
          {project.title ?? project.source_url ?? "Proyecto"}
        </h1>

        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-500">
          <span className={project.status === "FAILED" ? "text-rose-400" : undefined}>
            {PROJECT_STATUS_LABELS[project.status]}
          </span>
          {project.duration !== null && (
            <>
              <span aria-hidden="true">·</span>
              <span className="font-mono tabular-nums">{formatDuration(project.duration)}</span>
            </>
          )}
          {project.content_profile && (
            <>
              <span aria-hidden="true">·</span>
              <ProfileBadge
                profile={project.content_profile}
                speechRatio={project.speech_ratio}
              />
            </>
          )}
        </div>

        {project.error_message && (
          <p
            className={`mt-3 rounded-lg border px-3 py-2 text-sm ${
              project.status === "FAILED"
                ? "border-rose-500/30 bg-rose-500/10 text-rose-300"
                : "border-amber-500/30 bg-amber-500/10 text-amber-200"
            }`}
          >
            {project.error_message}
          </p>
        )}
      </header>

      {downloaded ? (
        <div ref={editorRef}>
          <ClipEditor
            project={project}
            timeline={timeline}
            candidates={list}
            onCreated={refreshCandidates}
          />
        </div>
      ) : (
        <p className="rounded-xl border border-dashed border-white/10 px-4 py-10 text-center text-sm text-zinc-500">
          Descargando el vídeo. El editor se abrirá en cuanto esté en disco.
        </p>
      )}

      <section aria-label="Clips del proyecto">
        <h2 className="mb-3 text-sm font-medium text-zinc-400">
          Clips
          <span className="ml-2 text-zinc-600">{list.length}</span>
        </h2>
        <CandidateManager
          candidates={list}
          profile={project.content_profile ?? "TALKING"}
          onChanged={refreshCandidates}
          onPreview={preview}
        />
      </section>
    </div>
  );
}

function ProfileBadge({
  profile,
  speechRatio,
}: {
  profile: "TALKING" | "VISUAL";
  speechRatio: number | null;
}) {
  const percentage = speechRatio === null ? null : (speechRatio * 100).toFixed(1);
  return (
    <span
      className="rounded border border-white/10 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-zinc-400"
      title={
        percentage === null
          ? undefined
          : `${percentage} % del vídeo tiene habla${
              profile === "VISUAL"
                ? "; por eso se ha juzgado por lo que ocurre, no por lo que se dice"
                : ""
            }`
      }
    >
      {profile === "VISUAL" ? "Visual" : "Hablado"}
      {percentage !== null && <span className="ml-1 text-zinc-600">{percentage} %</span>}
    </span>
  );
}

function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(Math.round(seconds % 60)).padStart(2, "0")}`;
}
