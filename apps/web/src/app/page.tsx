import { ProjectsPanel } from "@/components/ProjectsPanel";
import { SystemStatus } from "@/components/SystemStatus";
import { TodayBoard } from "@/components/TodayBoard";

export default function HomePage() {
  return (
    <main className="mx-auto w-full max-w-5xl px-6 py-10 sm:py-14">
      <header>
        <p className="text-xs font-medium uppercase tracking-[0.2em] text-zinc-500">ClipForge</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-tight text-zinc-50 sm:text-5xl">
          Convierte vídeos largos en clips
        </h1>
        <p className="mt-4 max-w-xl text-base leading-relaxed text-zinc-400">
          Detecta automáticamente los mejores momentos de un vídeo y los transforma en clips
          verticales listos para publicar.
        </p>
      </header>

      {/* Lo primero es lo que se hace a diario: subir lo que ya está listo.
          La configuración —buscador, canales, proyectos— va debajo, porque
          se toca una vez y luego casi nunca. */}
      <div className="mt-10">
        <TodayBoard />
      </div>

      <div className="mt-12">
        <ProjectsPanel />
      </div>

      <div className="mt-12">
        <SystemStatus />
      </div>
    </main>
  );
}
