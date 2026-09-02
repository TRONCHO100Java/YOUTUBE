# ClipForge

Convierte vídeos largos en clips verticales 9:16 listos para publicar: descarga, transcribe,
detecta los mejores momentos con IA, recorta y renderiza con aceleración NVIDIA.

> **Estado actual: FASE 2 completada** — pegas una URL de YouTube y el vídeo se descarga,
> se analiza con ffprobe y queda en `storage/` con sus metadatos. La transcripción con
> Whisper llega en la FASE 3.

---

## 1. Requisitos

| Herramienta | Versión usada | Notas |
|---|---|---|
| Python | **3.12** | *No usar 3.13/3.14*: `faster-whisper` (ctranslate2) y torch aún no publican wheels estables |
| Node.js | 20+ (probado en 24) | |
| Docker Desktop | 28+ | Solo para PostgreSQL y Redis |
| FFmpeg / FFprobe | 7+ (probado en 9.0) | Debe estar en el `PATH`, o configurar `FFMPEG_PATH` |
| Driver NVIDIA | 570+ | Necesario a partir de la FASE 3 (CUDA para Whisper y NVENC) |

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
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
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
│  │  │  ├─ services/           source/ (URLs), download/ (yt-dlp), video/ (ffprobe)
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
   └─ descarga con yt-dlp                (services/download/ytdlp.py)
   └─ lee metadatos reales con ffprobe   (services/video/probe.py)
   └─ guarda título, autor, duración, miniatura y ruta del vídeo
   └─ COMPLETED  (o FAILED con un mensaje legible)
```

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

## 9. Almacenamiento

```
storage/projects/{project_id}/
├─ source/        vídeo original      (KEEP_SOURCE_VIDEO)
├─ audio/         audio extraído      (KEEP_AUDIO)
├─ transcripts/   transcripciones
├─ clips/         clips finales       (siempre se conservan)
├─ subtitles/     .srt / .ass
└─ temp/          intermedios         (siempre se borran)
```

En base de datos se guardan **rutas relativas** a `STORAGE_PATH`, de modo que mover la carpeta o
migrar a S3/R2 no invalida los registros existentes.

## 10. Migraciones

```powershell
cd apps\backend
.\.venv\Scripts\alembic.exe revision --autogenerate -m "descripcion"
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe downgrade -1
```

Revisa siempre el fichero generado antes de aplicarlo.

## 11. Hoja de ruta

- [x] **FASE 1** — infraestructura, API, BD, worker, frontend
- [x] **FASE 2** — descarga con yt-dlp y creación de proyectos
- [ ] **FASE 3** — transcripción con faster-whisper sobre CUDA
- [ ] **FASE 4** — análisis de viralidad con LLM
- [ ] **FASE 5** — recorte y render vertical con FFmpeg/NVENC
- [ ] **FASE 6** — smart crop con detección de caras
- [ ] **FASE 7** — frontend completo con progreso y descarga
