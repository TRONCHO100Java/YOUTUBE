# ClipForge

Convierte vídeos largos en clips verticales 9:16 listos para publicar: descarga, transcribe,
detecta los mejores momentos con IA, recorta y renderiza con aceleración NVIDIA.

> **Estado actual: FASE 4 completada** — pegas una URL de YouTube y obtienes los mejores
> momentos del vídeo, puntuados sobre 100 y con sus timestamps exactos. El recorte y
> render en 9:16 llega en la FASE 5.

---

## 1. Requisitos

| Herramienta | Versión usada | Notas |
|---|---|---|
| Python | **3.12** | *No usar 3.13/3.14*: `faster-whisper` (ctranslate2) y torch aún no publican wheels estables |
| Node.js | 20+ (probado en 24) | |
| Docker Desktop | 28+ | Solo para PostgreSQL y Redis |
| FFmpeg / FFprobe | 7+ (probado en 9.0) | Debe estar en el `PATH`, o configurar `FFMPEG_PATH` |
| Driver NVIDIA | 570+ | Necesario a partir de la FASE 3 (CUDA para Whisper y NVENC) |
| Ollama | 0.5+ | Solo con `AI_PROVIDER=ollama` (el defecto). `ollama pull qwen2.5:14b` |

Comprobación rápida:

```powershell
py -3.12 --version
node --version
docker --version
ffmpeg -version
nvidia-smi
```

## 2. Puesta en marcha

```powershell
# 1. Configuración
Copy-Item .env.example .env          # ajusta lo que necesites

# 2. Infraestructura (PostgreSQL + Redis)
docker compose up -d

# 3. Entorno Python
cd apps\backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,gpu]"
.\.venv\Scripts\alembic.exe upgrade head

# 4. Frontend
cd ..\web
npm install
```

## 3. Arrancar en desarrollo

Cuatro procesos. Lo más cómodo es `.\start-dev.ps1`, que abre los tres últimos en ventanas
separadas; si prefieres control manual:

```powershell
# Terminal 0 — infraestructura (deja los contenedores en segundo plano)
docker compose up -d

# Terminal 1 — API
cd apps\backend
.\.venv\Scripts\uvicorn.exe clipforge.api.main:app --reload --port 8000

# Terminal 2 — worker
cd apps\backend
.\.venv\Scripts\celery.exe -A clipforge.worker.celery_app worker --loglevel=info --pool=solo -Q cpu,gpu

# Terminal 3 — frontend
cd apps\web
npm run dev
```

| Servicio | URL |
|---|---|
| Frontend | http://localhost:3000 |
| API | http://localhost:8000 |
| Documentación OpenAPI | http://localhost:8000/docs |
| PostgreSQL | `localhost:5442` |
| Redis | `localhost:6390` |

> **Puertos no estándar a propósito.** En esta máquina 5432/5433/5434 y 6379/6380 ya estaban
> ocupados por otros proyectos Docker. ClipForge usa 5442/6390 para no colisionar; se cambian
> en el `.env` (`POSTGRES_PORT`, `REDIS_PORT`) junto con `DATABASE_URL` y `REDIS_URL`.

`--pool=solo` es obligatorio en Windows: el pool `prefork` por defecto de Celery no funciona.

## 4. Verificar que todo está bien

```powershell
curl http://localhost:8000/health          # liveness
curl http://localhost:8000/health/ready    # PostgreSQL + Redis + worker
```

`/health/ready` devuelve el estado de cada dependencia y responde 503 si alguna falla.
La home del frontend muestra esa misma información.

## 5. Calidad

```powershell
# Backend
cd apps\backend
.\.venv\Scripts\python.exe -m pytest       # tests
.\.venv\Scripts\ruff.exe check .           # linter
.\.venv\Scripts\ruff.exe format .          # formato
.\.venv\Scripts\mypy.exe                   # tipado estricto
.\.venv\Scripts\alembic.exe check          # ¿hay modelos sin migrar?

# Frontend
cd apps\web
npm run typecheck
npm run lint
npm run build
```

## 6. Estructura

```
/
├─ apps/
│  ├─ backend/                  Python 3.12 — API y worker en un único paquete
│  │  ├─ alembic/               migraciones
│  │  ├─ src/clipforge/
│  │  │  ├─ core/               config, logging, errores, storage, rutas
│  │  │  ├─ db/                 engines, sesiones y modelos ORM
│  │  │  ├─ api/                app FastAPI, routers, schemas, dependencias
│  │  │  ├─ repositories/       acceso a datos
│  │  │  ├─ services/           source/ (URLs), download/ (yt-dlp),
│  │  │  │                      transcribe/ (Whisper), ai/ (LLM),
│  │  │  │                      video/ (ffmpeg/ffprobe)
│  │  │  └─ worker/             Celery: app y tareas
│  │  └─ tests/
│  └─ web/                      Next.js 16 + TypeScript strict + Tailwind 4
├─ storage/                     ficheros generados (ignorado por git)
├─ docker-compose.yml           PostgreSQL + Redis
└─ .env.example
```

### Por qué API y worker comparten paquete

Comparten modelos, configuración, sesiones y rutas de almacenamiento. Separarlos en dos
proyectos Python obligaría a duplicar todo eso o a mantener una librería común desde el primer
día. En su lugar hay **un paquete y dos puntos de entrada** (`uvicorn` y `celery worker`), que es
como se despliegan en producción.

El desacople que importa se mantiene: el worker no llama nunca a la API ni al revés; se comunican
por **Redis** (cola de trabajos) y **PostgreSQL** (estado). Mover los workers a otra máquina o a
RunPod solo requiere apuntarlos al mismo Redis y a la misma base de datos.

Las colas están separadas desde el principio: `cpu` para trabajo ligero y `gpu` para el pipeline
pesado (Whisper y FFmpeg).

## 7. API

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/projects` | Crea un proyecto desde una URL y encola su procesamiento |
| `GET` | `/api/projects` | Lista paginada |
| `GET` | `/api/projects/{id}` | Detalle, con `progress` para la barra de estado |
| `GET` | `/api/projects/{id}/transcript` | Transcripción con segmentos (`?include_words=true` añade los tiempos por palabra) |
| `GET` | `/api/projects/{id}/candidates` | Momentos detectados, con su desglose de puntuación |
| `POST` | `/api/projects/{id}/retry` | Reprocesa un proyecto terminado o fallido |
| `DELETE` | `/api/projects/{id}` | Borra el proyecto y sus ficheros en disco |
| `GET` | `/health`, `/health/ready` | Liveness y readiness |

Todos los errores comparten la misma forma:

```json
{ "error": { "code": "unsupported_source", "message": "Host no permitido: vimeo.com", "details": {} } }
```

### Pipeline

```
POST /api/projects
   └─ valida y normaliza la URL          (services/source/urls.py)
   └─ crea el Project en estado CREATED
   └─ encola clipforge.pipeline.process_project en la cola `gpu`

worker
   └─ DOWNLOADING
   │    └─ descarga con yt-dlp             (services/download/ytdlp.py)
   │    └─ metadatos reales con ffprobe    (services/video/probe.py)
   └─ TRANSCRIBING
   │    └─ extrae audio WAV 16 kHz mono    (services/video/audio.py)
   │    └─ faster-whisper sobre CUDA       (services/transcribe/whisper.py)
   │    └─ guarda Transcript + segmentos con timestamps por palabra
   └─ ANALYZING
   │    └─ trocea en ventanas solapadas    (services/ai/chunking.py)
   │    └─ un LLM propone momentos por ventana
   │    └─ valida, deduplica y rankea      (services/ai/resolver.py, ranking.py)
   │    └─ guarda los ClipCandidate puntuados
   └─ COMPLETED  (o FAILED con un mensaje legible)
```

En un reintento la descarga se salta si el vídeo sigue en disco, y la transcripción
anterior se borra antes de guardar la nueva: nunca quedan dos.

La descarga se ejecuta **fuera de toda transacción**: puede durar minutos y no debe
mantener ocupada una conexión de PostgreSQL. El estado se actualiza en transacciones
cortas e independientes.

### Validación de fuentes

`validate_source_url` es la única puerta de entrada de contenido. Rechaza esquemas que no
sean `http`/`https`, hosts fuera de `ALLOWED_SOURCE_HOSTS`, URLs con credenciales embebidas
e identificadores mal formados; y **normaliza** cualquier variante (`youtu.be`, `/shorts/`,
`/embed/`, `/live/`, parámetros de lista y tracking) a `https://www.youtube.com/watch?v=ID`.

El nombre del fichero en disco se deriva del id ya validado (`{video_id}.mp4`), nunca del
título elegido por un tercero.

## 8. Modelo de datos

```
Project ──1:1── Transcript ──1:N── TranscriptSegment
   │
   └──1:N── ClipCandidate ──1:1── GeneratedClip
```

Todas las claves primarias son UUIDv4 generadas en cliente. Los estados de `Project` son
`CREATED → DOWNLOADING → TRANSCRIBING → ANALYZING → GENERATING_CLIPS → COMPLETED`, con `FAILED`
como estado terminal alternativo.

`TranscriptSegment.index` es el identificador estable que se le ofrecerá al LLM para seleccionar
rangos: **el modelo elige segmentos, nunca inventa timestamps**. El backend deriva los tiempos
exactos a partir de los segmentos reales.

## 9. Transcripción

Motor: **faster-whisper** (ctranslate2) sobre CUDA. Configurable por entorno:

```
WHISPER_MODEL=large-v3       # tiny | base | small | medium | large-v3
WHISPER_DEVICE=cuda          # cuda | cpu | auto
WHISPER_COMPUTE_TYPE=float16
WHISPER_WORD_TIMESTAMPS=true
WHISPER_VAD_FILTER=true
```

El audio se extrae a **WAV PCM 16 kHz mono**, que es justo la entrada que espera Whisper:
así el modelo no remuestrea y el fichero sirve tal cual para pasadas futuras.

El modelo se carga **una vez por proceso** y se reutiliza entre tareas. La primera carga
descarga ~3 GB desde Hugging Face; a partir de ahí tarda unos segundos.

Con `WHISPER_DEVICE=cuda` y sin GPU utilizable, el sistema **falla de forma ruidosa** en
lugar de caer a CPU: large-v3 en CPU tarda órdenes de magnitud más y conviene enterarse.

### Rendimiento medido (RTX 5080, large-v3, float16)

| | |
|---|---|
| Carga del modelo (primera vez, con descarga) | ~106 s |
| Carga del modelo (posteriores) | ~3 s |
| Transcripción | **~14x tiempo real** |
| Ejemplo: vídeo de 9:39 | 39 s, 103 segmentos, 1228 timestamps de palabra |

### Librerías CUDA en Windows

ctranslate2 carga cuBLAS y cuDNN **por nombre**, usando el orden de búsqueda de DLL por
defecto de Windows: consulta el `PATH`, pero **no** los directorios registrados con
`os.add_dll_directory`. Como esas librerías se instalan por pip dentro de
`site-packages/nvidia/*/bin`, sin prepararlas falla con:

```
RuntimeError: Library cublas64_12.dll is not found or cannot be loaded
```

`clipforge/core/cuda.py` lo resuelve añadiendo esos directorios al `PATH` del proceso antes
de cargar el primer modelo. Se llama solo, no hay que hacer nada.

Para una **RTX 50xx (Blackwell, sm_120)** hacen falta cuBLAS 12.8+ y cuDNN 9; el extra
`gpu` del `pyproject.toml` ya fija esas versiones mínimas.

## 10. Análisis de viralidad

El LLM **no ve el vídeo ni escribe timestamps**: recibe los segmentos de la transcripción
numerados y devuelve rangos de índices. El backend deriva los tiempos exactos a partir de
esos segmentos, de modo que es imposible que se invente un instante que no existe.

```
[5]  0:43 - 0:52 | No puedes salir vivo de la vida...
[6]  0:52 - 1:01 | ...
        ↓ el modelo responde  {"start_segment": 5, "end_segment": 10, ...}
        ↓ el backend calcula  start_time = segmento[5].start_time
```

### Estrategia

Una transcripción de una hora no cabe cómodamente en una llamada, y aunque cupiera el
modelo pierde precisión. Se trocea en ventanas de `ANALYSIS_CHUNK_SECONDS` con
`ANALYSIS_CHUNK_OVERLAP_SECONDS` de solape, para que un buen momento a caballo entre dos
ventanas aparezca entero en al menos una:

```
troceado → análisis por ventana → validación → deduplicación → ranking → top N
```

El fallo de una ventana **no aborta el proyecto**: se registra y se sigue. Solo se propaga
el error si fallan todas.

### Puntuación

| Dimensión | Máximo | Qué mide |
|---|---:|---|
| `hook` | 20 | Fuerza de los primeros segundos para frenar el scroll |
| `curiosity` | 20 | Necesidad de seguir viendo que genera |
| `emotion` | 15 | Intensidad emocional |
| `clarity` | 15 | Se entiende sin contexto previo |
| `value` | 15 | Enseña, resuelve o informa |
| `shareability` | 10 | Ganas de compartirlo o debatirlo |
| `duration` | 5 | Cercanía a la duración ideal |

**El total lo suma el backend, no el modelo.** Los LLM se equivocan sumando, y un total
incoherente con su propio desglose es imposible de depurar.

### Validación de lo que devuelve el modelo

Todo lo que llega del LLM se trata como no fiable:

- Índices fuera de la ventana → se descarta el candidato.
- Rango invertido (`end < start`) → se corrige solo.
- Puntuaciones fuera de rango → se acotan.
- Clip demasiado largo → se recorta por el final; demasiado corto → se extiende. Si aun así
  no entra en `MIN_CLIP_DURATION`–`MAX_CLIP_DURATION`, se descarta.
- Candidatos que solapan más del 50% → se conserva el mejor puntuado.

### Proveedores

```
AI_PROVIDER=ollama          # ollama | openai | anthropic
AI_MODEL=qwen2.5:14b
```

El pipeline depende solo de la interfaz `ClipAnalyzer`; cambiar de proveedor es cambiar una
variable de entorno. Los tres usan **el mismo prompt y el mismo esquema JSON**, cada uno con
su mecanismo de salida estructurada.

`ollama` es el defecto: local, gratis y sin enviar la transcripción a un tercero. Requiere
tener Ollama corriendo y el modelo descargado (`ollama pull qwen2.5:14b`). Como se habla con
él por HTTP directo — y un modelo local devuelve de vez en cuando una respuesta inservible —
el cliente reintenta hasta `AI_MAX_RETRIES` veces; los SDK de OpenAI y Anthropic ya
reintentan por su cuenta.

## 11. Almacenamiento

```
storage/projects/{project_id}/
├─ source/        vídeo original      (KEEP_SOURCE_VIDEO, por defecto se conserva)
├─ audio/         WAV 16 kHz mono     (KEEP_AUDIO, se borra tras transcribir)
├─ transcripts/   transcripciones
├─ clips/         clips finales       (siempre se conservan)
├─ subtitles/     .srt / .ass
└─ temp/          intermedios         (siempre se borran)
```

En base de datos se guardan **rutas relativas** a `STORAGE_PATH`, de modo que mover la carpeta o
migrar a S3/R2 no invalida los registros existentes.

## 12. Migraciones

```powershell
cd apps\backend
.\.venv\Scripts\alembic.exe revision --autogenerate -m "descripcion"
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe downgrade -1
```

Revisa siempre el fichero generado antes de aplicarlo.

## 13. Hoja de ruta

- [x] **FASE 1** — infraestructura, API, BD, worker, frontend
- [x] **FASE 2** — descarga con yt-dlp y creación de proyectos
- [x] **FASE 3** — transcripción con faster-whisper sobre CUDA
- [x] **FASE 4** — análisis de viralidad con LLM
- [ ] **FASE 5** — recorte y render vertical con FFmpeg/NVENC
- [ ] **FASE 6** — smart crop con detección de caras
- [ ] **FASE 7** — frontend completo con progreso y descarga
