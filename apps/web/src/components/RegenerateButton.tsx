"use client";

interface Props {
  /** Etiqueta en reposo: "Reintentar" si falló, "Regenerar" si terminó. */
  label: string;
  /** Segundo clic pendiente: rehacer un proyecto terminado tira lo que ya había. */
  confirming: boolean;
  busy: boolean;
  onClick: () => void;
  onBlur: () => void;
  title?: string;
}

export function RegenerateButton({
  label,
  confirming,
  busy,
  onClick,
  onBlur,
  title,
}: Props) {
  return (
    <button
      type="button"
      onClick={onClick}
      onBlur={onBlur}
      disabled={busy}
      title={title}
      className={`shrink-0 rounded-lg border px-3 py-1.5 text-xs transition disabled:opacity-50 ${
        confirming
          ? "border-amber-500/40 text-amber-300 hover:border-amber-400/60"
          : "border-white/10 text-zinc-300 hover:border-white/20 hover:text-zinc-100"
      }`}
    >
      {busy ? "Enviando…" : confirming ? "¿Rehacer?" : label}
    </button>
  );
}
