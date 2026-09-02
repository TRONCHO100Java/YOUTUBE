import { RecentProjects } from "@/components/RecentProjects";
import { SystemStatus } from "@/components/SystemStatus";

export default function HomePage() {
  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-16 sm:py-24">
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

      <div className="mt-12">
        <SystemStatus />
        <RecentProjects />
      </div>
    </main>
  );
}
