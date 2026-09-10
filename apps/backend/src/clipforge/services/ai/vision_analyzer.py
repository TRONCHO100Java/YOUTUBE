"""Análisis de momentos a partir de fotogramas, para vídeos sin diálogo.

Es la respuesta al problema que motivó todo esto: una recopilación de comedia
física de la que Whisper sacó quince caracteres alucinados. Ningún analizador
de texto puede juzgar eso, por bueno que sea el modelo. Este sí, porque mira.

El flujo es el mismo de siempre —el modelo elige, el backend calcula los
tiempos— solo que aquí elige entre bloques de fotogramas en lugar de entre
índices de segmento.

Los tres proveedores hablan de imágenes de forma distinta (Ollama las quiere en
un campo `images` aparte; OpenAI y Anthropic, como bloques dentro del mensaje),
así que solo cambia el envío: prompt, esquema y validación son comunes.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

from clipforge.core.config import settings
from clipforge.core.errors import ExternalToolError
from clipforge.core.logging import get_logger
from clipforge.services.ai.base import (
    AnalysisContext,
    BlockAnalyzer,
    ClipSuggestion,
)
from clipforge.services.ai.profiles import ProfileRules, rules_for
from clipforge.services.ai.prompts import build_system_prompt, build_vision_prompt
from clipforge.services.ai.resolver import resolve_vision_candidates
from clipforge.services.ai.schema import parse_analysis, response_json_schema
from clipforge.services.signals.base import MomentBlock
from clipforge.services.video.frames import Frame, extract_frames

logger = get_logger(__name__)

#: Modelo por defecto de cada proveedor cuando `AI_VISION_MODEL` trae el de otro.
DEFAULT_MODELS = {
    "ollama": "qwen2.5vl:7b",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-opus-5",
}

MAX_TOKENS = 16000

#: Espera entre reintentos con Ollama, igual que en el analizador de texto.
RETRY_BACKOFF_SECONDS = 1.0

#: Coste aproximado en tokens de un fotograma de 512 px, medido contra
#: qwen2.5vl: cinco imágenes ocupan unos 6.100 tokens de prompt.
TOKENS_PER_FRAME = 1150

#: Espacio para el prompt del sistema, el esquema y la respuesta.
BASE_CONTEXT_TOKENS = 4096

#: Techo del contexto. Pasarse de aquí no da error: simplemente reserva más
#: memoria de la que hace falta.
MAX_CONTEXT_TOKENS = 32768


def context_size(frame_count: int) -> int:
    """Contexto necesario para una petición con `frame_count` imágenes.

    Se calcula en lugar de fijarlo porque quedarse corto no degrada nada: Ollama
    rechaza la petición entera con un 400 sin explicación. Con el valor fijo de
    16.384 que se usaba, tres bloques de cinco fotogramas ya no cabían.
    """
    return min(MAX_CONTEXT_TOKENS, BASE_CONTEXT_TOKENS + frame_count * TOKENS_PER_FRAME)


class VisionClipAnalyzer(BlockAnalyzer):
    """Implementación de `BlockAnalyzer` sobre un modelo multimodal."""

    def __init__(self, provider: str | None = None, model: str | None = None) -> None:
        self.provider = (provider or settings.ai_vision_provider or settings.ai_provider).lower()
        if self.provider not in DEFAULT_MODELS:
            raise ExternalToolError(
                f"Proveedor de visión desconocido: '{self.provider}'",
                details={"supported": sorted(DEFAULT_MODELS)},
            )
        self.model = model or settings.ai_vision_model or DEFAULT_MODELS[self.provider]

    # ------------------------------------------------------------------ público
    def analyze_blocks(
        self,
        blocks: Sequence[MomentBlock],
        context: AnalysisContext,
        *,
        video_path: Path,
        workdir: Path,
    ) -> list[ClipSuggestion]:
        """Enseña los bloques al modelo, por tandas, y devuelve los que valen.

        Los bloques NO se mandan todos en una petición. Quince bloques son
        setenta y cinco imágenes, y eso Ollama lo rechaza con un 400 seco; pero
        aunque cupieran, repartir la atención del modelo entre setenta y cinco
        fotogramas hace que juzgue peor cada uno. Se trocea igual que el
        análisis de texto trocea la transcripción en ventanas.

        El fallo de una tanda no aborta el análisis: se registra y se sigue con
        las demás. Solo se propaga el error si fallan todas.

        Raises:
            ExternalToolError: si no se puede extraer ni un solo fotograma, o si
                todas las tandas fallan.
        """
        if not blocks:
            return []

        rules = rules_for(context.profile)
        started = time.perf_counter()

        frames_by_block = self._collect_frames(blocks, video_path, workdir)
        pairs = [
            (block, frames) for block, frames in zip(blocks, frames_by_block, strict=True) if frames
        ]
        if not pairs:
            raise ExternalToolError(
                "No se ha podido extraer ningún fotograma del vídeo para analizarlo"
            )

        size = max(1, settings.vision_blocks_per_request)
        batches = [pairs[index : index + size] for index in range(0, len(pairs), size)]

        resolved: list[ClipSuggestion] = []
        proposed = 0
        failures: list[str] = []

        for number, batch in enumerate(batches, start=1):
            batch_blocks = [block for block, _ in batch]
            batch_frames = [frame for _, frames in batch for frame in frames]
            prompt = build_vision_prompt(
                batch_blocks, context, frames_per_block=settings.vision_frames_per_block
            )
            try:
                raw_candidates = self._request(
                    rules, prompt, batch_frames, keywords=bool(context.keywords)
                )
            except ExternalToolError as exc:
                logger.warning("ai.vision_batch_failed", batch=number, error=exc.message)
                failures.append(exc.message)
                continue

            proposed += len(raw_candidates)
            # Los bloques se numeran desde 1 dentro de cada tanda, así que la
            # resolución se hace contra los de esta y no contra la lista entera.
            resolved.extend(resolve_vision_candidates(raw_candidates, batch_blocks, rules))

        if failures and len(failures) == len(batches):
            raise ExternalToolError(
                "El análisis visual ha fallado en todas las tandas",
                details={"first_error": failures[0], "batches": len(batches)},
            )

        logger.info(
            "ai.vision_analyzed",
            provider=self.provider,
            model=self.model,
            blocks=len(pairs),
            batches=len(batches),
            failed_batches=len(failures),
            proposed=proposed,
            resolved=len(resolved),
            seconds=round(time.perf_counter() - started, 1),
        )
        return resolved

    # ----------------------------------------------------------------- privado
    def _collect_frames(
        self, blocks: Sequence[MomentBlock], video_path: Path, workdir: Path
    ) -> list[list[Frame]]:
        """Fotogramas de cada bloque, en el mismo orden que los bloques."""
        return [
            extract_frames(
                video_path,
                workdir,
                start=block.start,
                end=block.end,
                prefix=f"b{index:02d}",
            )
            for index, block in enumerate(blocks)
        ]

    def _request(
        self,
        rules: ProfileRules,
        prompt: str,
        frames: Sequence[Frame],
        *,
        keywords: bool = False,
    ) -> list[Any]:
        system = build_system_prompt(rules, vision=True, keywords=keywords)
        schema = response_json_schema(rules, vision=True)

        if self.provider == "ollama":
            content = self._request_ollama(system, prompt, frames, schema)
        elif self.provider == "openai":
            content = self._request_openai(system, prompt, frames, schema)
        else:
            content = self._request_anthropic(system, prompt, frames, schema)

        return parse_analysis(content, rules, vision=True)

    def _request_ollama(
        self, system: str, prompt: str, frames: Sequence[Frame], schema: dict[str, Any]
    ) -> str:
        """Ollama recibe las imágenes en un campo `images` del propio mensaje."""
        base_url = settings.ollama_base_url.rstrip("/")
        payload = {
            "model": self.model,
            "stream": False,
            "format": schema,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": prompt,
                    "images": [frame.to_base64() for frame in frames],
                },
            ],
            "options": {
                # Determinista, igual que el análisis de texto: dos ejecuciones
                # sobre el mismo vídeo deben dar el mismo ranking.
                "temperature": 0,
                "num_ctx": context_size(len(frames)),
            },
        }

        attempts = max(1, settings.ai_max_retries)
        last_error: ExternalToolError | None = None
        for attempt in range(1, attempts + 1):
            try:
                response = httpx.post(
                    f"{base_url}/api/chat",
                    json=payload,
                    # Un modelo de visión local sobre decenas de imágenes tarda
                    # bastante más que uno de texto.
                    timeout=settings.ai_request_timeout_seconds * 4,
                )
                response.raise_for_status()
                content = (response.json().get("message") or {}).get("content")
                if not content:
                    raise ExternalToolError("Ollama ha devuelto una respuesta vacía")
                return str(content)
            except httpx.HTTPStatusError as exc:
                last_error = ExternalToolError(
                    f"Ollama ha respondido {exc.response.status_code}",
                    details={"body": exc.response.text[:500]},
                )
            except httpx.HTTPError as exc:
                last_error = ExternalToolError(
                    f"No se ha podido contactar con Ollama en {base_url}. "
                    "¿Está arrancado? (`ollama serve`)",
                    details={"error": str(exc)},
                )
            except ExternalToolError as exc:
                last_error = exc

            if attempt < attempts:
                logger.warning("ai.vision_retry", attempt=attempt, error=last_error.message)
                time.sleep(RETRY_BACKOFF_SECONDS)

        assert last_error is not None
        raise last_error

    def _request_openai(
        self, system: str, prompt: str, frames: Sequence[Frame], schema: dict[str, Any]
    ) -> str:
        from openai import OpenAI, OpenAIError

        if not settings.openai_api_key:
            raise ExternalToolError("El análisis visual usa OpenAI pero falta OPENAI_API_KEY")

        client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.ai_request_timeout_seconds * 4,
            max_retries=settings.ai_max_retries,
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content += [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{frame.to_base64()}"},
            }
            for frame in frames
        ]

        try:
            # Los tipos del SDK son TypedDicts cerrados y el contenido se arma
            # aqui en tiempo de ejecucion; la validacion real la hace el propio
            # cliente al serializar.
            completion = client.chat.completions.create(  # type: ignore[call-overload]
                model=self.model,
                temperature=0,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": content},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "vision_analysis",
                        "strict": True,
                        "schema": schema,
                    },
                },
            )
        except OpenAIError as exc:
            raise ExternalToolError(
                "La llamada de visión a OpenAI ha fallado", details={"error": str(exc)[:500]}
            ) from exc

        text = completion.choices[0].message.content if completion.choices else None
        if not text:
            raise ExternalToolError("OpenAI ha devuelto una respuesta vacía")
        return str(text)

    def _request_anthropic(
        self, system: str, prompt: str, frames: Sequence[Frame], schema: dict[str, Any]
    ) -> str:
        import anthropic

        if not settings.anthropic_api_key:
            raise ExternalToolError("El análisis visual usa Anthropic pero falta ANTHROPIC_API_KEY")

        client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=float(settings.ai_request_timeout_seconds * 4),
            max_retries=settings.ai_max_retries,
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        content += [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": frame.to_base64(),
                },
            }
            for frame in frames
        ]

        try:
            message = client.messages.create(  # type: ignore[call-overload]
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": content}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.APIError as exc:
            raise ExternalToolError(
                "La llamada de visión a Anthropic ha fallado", details={"error": str(exc)[:500]}
            ) from exc

        if message.stop_reason == "refusal":
            raise ExternalToolError(
                "Anthropic ha rechazado la petición por sus filtros de seguridad"
            )

        text = next((block.text for block in message.content if block.type == "text"), None)
        if not text:
            raise ExternalToolError("Anthropic ha devuelto una respuesta vacía")
        return str(text)
