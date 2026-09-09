import { ProjectWorkspace } from "@/components/ProjectWorkspace";

/**
 * Editor de un proyecto.
 *
 * Es una página propia y no un desplegable dentro de la lista porque necesita
 * todo el ancho: el reproductor, la línea de tiempo de señales y la lista de
 * clips no caben en una tarjeta.
 */
export default async function ProjectPage({ params }: PageProps<"/projects/[id]">) {
  const { id } = await params;

  return (
    <main className="mx-auto w-full max-w-5xl px-6 py-10">
      <ProjectWorkspace projectId={id} />
    </main>
  );
}
