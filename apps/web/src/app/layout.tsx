import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "ClipForge",
  description: "Convierte vídeos largos en clips verticales listos para publicar.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="es" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      {/*
        Las extensiones del navegador escriben en el <body> antes de que React
        hidrate —un `__processed_<uuid>__` distinto en cada carga—, y eso React
        lo cuenta como que el servidor y el cliente no coinciden. No es nuestro
        y no se puede evitar desde aquí: depende de qué tenga instalado quien
        mira la página.

        La supresión afecta SOLO a este elemento, no a lo que lleva dentro, así
        que un desajuste de verdad en cualquier componente se sigue viendo.
      */}
      <body className="min-h-full" suppressHydrationWarning>
        {children}
      </body>
    </html>
  );
}
