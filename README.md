# ClipForge

Convierte vídeos largos en clips verticales 9:16 listos para publicar: descarga, transcribe,
detecta los mejores momentos con IA, recorta y renderiza con aceleración NVIDIA.

> **Estado actual: FASE 5 completada** — pegas una URL de YouTube y obtienes clips
> verticales 1080x1920 ya renderizados, con subtítulos incrustados y acelerados por la
> GPU, reproducibles y descargables desde el navegador.

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
│  │  │  │                      transcribe/ (Whisper), ai/ (LLM y visión),
│  │  │  │                      signals/ (volumen, cortes de plano, movimiento),
│  │  │  │                      video/ (ffmpeg: encoder, crop, letterbox,
│  │  │  │                      framing, fotogramas, render), subtitles/,
│  │  │  │                      render_clip.py (render de un clip suelto)
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
| `GET` | `/api/search` | Busca vídeos en YouTube (`?q=`, filtros de duración y vistas) |
| `POST` | `/api/projects/batch` | Encola varias URLs de una vez |
| `GET` `POST` | `/api/channels` | Canales vigilados: listar y dar de alta |
| `PATCH` `DELETE` | `/api/channels/{id}` | Pausar, editar filtros o dejar de vigilar |
| `POST` | `/api/channels/{id}/check` | Revisar un canal ahora, sin esperar al temporizador |
| `POST` | `/api/projects` | Crea un proyecto desde una URL y encola su procesamiento |
| `GET` | `/api/projects` | Lista paginada |
| `GET` | `/api/projects/{id}` | Detalle, con `progress` para la barra de estado |
| `PATCH` | `/api/projects/{id}` | Cambia las palabras clave del proyecto |
| `GET` | `/api/projects/{id}/transcript` | Transcripción con segmentos (`?include_words=true` añade los tiempos por palabra) |
| `GET` | `/api/projects/{id}/candidates` | Momentos detectados, con su desglose de puntuación |
| `POST` | `/api/projects/{id}/candidates` | Crea un clip recortado a mano (`start_time`, `end_time`, `title`) |
| `GET` | `/api/projects/{id}/signals` | Curva de volumen, cortes de plano, movimiento y bloques candidatos |
| `GET` | `/api/projects/{id}/source` | El vídeo original. Admite `Range`, para poder recortarlo en el navegador |
| `POST` | `/api/projects/{id}/retry` | Reprocesa un proyecto terminado o fallido |
| `POST` | `/api/projects/{id}/retitle` | Reescribe solo los títulos. No re-renderiza |
| `DELETE` | `/api/projects/{id}` | Borra el proyecto y sus ficheros en disco |
| `GET` | `/api/projects/{id}/clips` | Clips renderizados, con resolución, peso y encoder usado |
| `GET` | `/api/clips/{id}` | Detalle de un clip |
| `GET` | `/api/clips/{id}/video` | El MP4. Admite `Range`, así que el `<video>` puede buscar sin descargarlo entero |
| `GET` | `/api/clips/{id}/subtitles` | El `.srt` como fichero aparte |
| `POST` | `/api/clips/{id}/publish` | Sube el clip a YouTube |
| `GET` | `/api/candidates/{id}` | Detalle de un candidato |
| `PATCH` | `/api/candidates/{id}` | Ajusta entrada, salida, título, gancho o estado |
| `POST` | `/api/candidates/{id}/render` | Encola el render de ese único clip |
| `DELETE` | `/api/candidates/{id}` | Borra el candidato y su clip |
| `GET` | `/api/tasks/{task_id}` | Estado de una tarea encolada |
| `GET` | `/health`, `/health/ready` | Liveness y readiness |

El navegador solo ve las cabeceras de respuesta que CORS le expone explícitamente. Sin
`Content-Range` en `expose_headers` la etiqueta `<video>` no puede resolver el tamaño del
recurso y se queda cargando para siempre, aunque el servidor responda un 206 correcto.

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
   └─ GENERATING_CLIPS
   │    └─ resuelve el encoder una vez        (services/video/encoder.py)
   │    └─ detecta el letterbox del original  (services/video/letterbox.py)
   │    └─ por cada candidato: .srt + .ass    (services/subtitles/)
   │    └─ corta, recorta, escala y codifica  (services/video/render.py)
   │    └─ guarda los GeneratedClip
   └─ COMPLETED  (o FAILED con un mensaje legible)
```

En un reintento la descarga se salta si el vídeo sigue en disco, y la transcripción
anterior se borra antes de guardar la nueva: nunca quedan dos.

Que falle el render de un clip no tumba la fase entera: se registra el fallo y se sigue con
el resto. Perder uno de cinco clips es mejor que perder los cinco.

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

### Palabras clave del usuario

Al crear el proyecto se puede escribir **de qué va el vídeo y quién sale**:
`Kai Cenat, Speed, Among Us`. Es la única información que el sistema no puede
sacar por su cuenta —el título de YouTube rara vez nombra a los streamers que
aparecen, y la transcripción usa apodos que nadie busca— y es justo la que
hace que un Short salga en la búsqueda de alguien.

Se guardan tal y como se escriben (`projects.keywords`) y se parten al usarlas,
no al guardarlas, para que el campo del formulario devuelva lo tecleado. Llegan
al prompt en dos sitios: la cabecera del mensaje (son datos de ESTE vídeo) y
una regla que gobierna cómo usarlas.

La regla tiene dos mitades y las dos importan: **úsalas cuando encajen** —un
nombre propio vale más que cualquier adjetivo— y **no las metas a la fuerza**,
porque un título que promete algo que el clip no enseña pierde al espectador en
dos segundos, y eso se paga en retención.

`PATCH /api/projects/{id}` las cambia después sin volver a descargar el vídeo.
No relanza nada por su cuenta: solo influyen en el análisis, así que aplicarlas
a un proyecto terminado es pulsar Regenerar, y esa decisión es del usuario.

### Titulado

El título que sale del análisis es un **subproducto**. Ese modelo está
repartiendo cien puntos entre siete dimensiones y el título lo escribe de paso,
así que nombra la escena en lugar de venderla: *"La fiesta de colores"*, *"El
salto del niño"*. Eso es una etiqueta de archivo, no un título de YouTube.

`services/ai/titles.py` lo arregla separando el trabajo. Corre **después** de la
selección, sobre los clips que van a existir de verdad, así que cuesta **una
llamada por proyecto** en lugar de una por ventana de transcripción. A ese
precio se puede pagar un modelo bueno aunque el análisis corra en local:
`AI_TITLE_PROVIDER` y `AI_TITLE_MODEL` desvían solo esta llamada.

Los clips van todos en la misma petición, y no uno por uno, por una razón que
no es el coste: el modelo ve los demás mientras escribe cada título. Es lo
único que evita que cinco clips del mismo vídeo acaben con cinco variaciones de
la misma frase.

Se piden varias variantes por clip y se acepta **la primera que pasa el filtro**:

| Se descarta | Por qué |
|---|---|
| Más de `TITLE_MAX_CHARS` | El móvil corta el resto |
| Tópicos (*"you won't believe"*, *"must watch"*, *"funny moment"*) | Se pasa de largo |
| TODO EN MAYÚSCULAS | Parece spam |
| Igual que el gancho | Ya va escrito en pantalla: se gastarían los dos textos en decir lo mismo |
| Mismo arranque que otro del lote | Son clips del mismo vídeo y se ven seguidos |

Si ninguna variante pasa limpia, se recorta la mejor por la última palabra que
quepa. Si aun así no queda nada, **manda el título del análisis**: peor, pero
real. Y si la llamada entera falla, se registra y los clips salen como estaban.
El titulado es una mejora, no un requisito.

**Las variantes que no se usan se guardan** (`clip_candidates.title_variants`).
La llamada ya está pagada, así que cambiar de título es un clic en el editor —no
otra llamada al modelo—, y las alternativas que se ofrecen han pasado el mismo
filtro que la elegida.

### Retitular sin re-renderizar

El título **no está dentro del MP4**. Cambiarlo es cambiar una fila y renombrar un
enlace, así que exigir un reprocesado completo —descarga, Whisper, análisis,
ffmpeg— para probar otro título era cobrar horas de GPU por un trabajo de
segundos. El botón **Retitular** vuelve a llamar al redactor sobre los candidatos
que ya existen y regenera la carpeta de exportación. Nada más.

Es también la forma de aplicar unas palabras clave que se escribieron tarde.

Dos cosas que **no** hace, y por el mismo motivo:

- **No toca el gancho.** Ese sí va incrustado en los píxeles; cambiarlo sin
  renderizar dejaría la base de datos diciendo una cosa y el vídeo enseñando otra.
- **No toca los clips manuales.** Su título lo ha escrito una persona.

Va a la cola ligera (`clipforge.titles.*`, fuera de la ruta de `clipforge.
pipeline.*`): no necesita la tarjeta, así que con un segundo worker no tendrá que
esperar detrás de una transcripción.

El botón **espera a que termine**, y eso no es un detalle. Un botón que encola
trabajo y devuelve 200 no dice nada: la petición ha ido bien, pero el trabajo ni
ha empezado, y "no ha pasado nada" y "está tardando" se ven exactamente igual. La
conclusión razonable, desde fuera, es que la aplicación está rota.

`GET /api/tasks/{task_id}` saca el estado que Celery ya guarda en Redis
(`task_track_started`), así que no hay estado nuevo que mantener. La interfaz
encola, se queda con el id, pregunta cada segundo y medio y al acabar dice
cuántos títulos han cambiado. `PENDING` es ambiguo —Celery no distingue
"encolada" de "no la conozco"— y por eso lo que se mira es `ready`, no el nombre
del estado: para quien espera, las dos son "todavía no".

### Lo que se pega en YouTube

El redactor no escribe solo el título: escribe también la **descripción** y las
**etiquetas**. La etiqueta `shorts` la pone el sistema siempre —es la que decide
que el vídeo entre en el carrusel, y olvidarla cuesta demasiado como para dejarla
a criterio del modelo— y el resto se normalizan a una palabra pegada sin
almohadilla: "Kai Cenat" se busca como `#KaiCenat`.

El **crédito al canal original lo compone el backend**, no el modelo: el modelo no
conoce la URL, y el crédito es justo lo que separa un clip de un reupload a ojos
de YouTube. No es decoración.

En la carpeta de exportación, junto a cada `NN - título.mp4`:

```
storage/export/{título del vídeo}/
├── 01 - Farmer slips into the mud and water.mp4
├── 01 - Farmer slips into the mud and water.txt   ← título, descripción, etiquetas, crédito
└── youtube.csv                                     ← los cinco en una tabla, para subir en tanda
```

El `.txt` va en bloques, en el mismo orden en que los pide el formulario de
YouTube, para poder copiar de arriba abajo. El CSV usa punto y coma porque Excel
en español con coma lo mete todo en una columna, y ahí deja de servir para lo
único que sirve. La descripción del CSV lleva el crédito ya incorporado: se abre
en otro programa, y volver aquí a por él no vale.

### Idioma de los textos

**El título y el gancho van siempre en inglés**, sea cual sea el idioma del vídeo. Son
los dos textos que se publican —el gancho además se incrusta en pantalla— y el público
objetivo de TikTok, Reels y Shorts es angloparlante. Si lo que se dice en el vídeo está
en otro idioma, el modelo lo traduce.

El **motivo** es la excepción y se queda en español: no sale del sistema, es la nota que
lee quien revisa los candidatos en el editor.

Los subtítulos incrustados no entran en esta regla: son la transcripción literal del
audio, así que hablan el idioma del vídeo.

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

## 11. Render vertical y subtítulos

Un solo paso de ffmpeg por clip: buscar, recortar, escalar, quemar subtítulos y codificar.
Cortar a un fichero intermedio y recodificarlo después costaría el doble de tiempo y una
generación más de pérdida de calidad.

```
-ss {inicio} -t {duracion} -i original.mp4
  -vf crop=...,scale=1080:1920:flags=lanczos,setsar=1,ass=clip.ass
  -c:v h264_nvenc -preset p5 -tune hq -rc vbr ...
  -c:a aac -b:a 192k -movflags +faststart
```

`-ss` va **antes** de `-i` para que ffmpeg busque por el índice del contenedor en vez de
decodificar desde el principio; como después se recodifica, el corte sigue siendo exacto al
fotograma. `-movflags +faststart` mueve el índice al principio del MP4: sin él el navegador
tiene que descargar el fichero entero antes de empezar a reproducir.

### Encoder

```
VIDEO_ENCODER=auto           # auto | h264_nvenc | libx264
```

`auto` **comprueba** NVENC en vez de suponerlo: codifica dos fotogramas de prueba a `-f null`
y solo lo usa si funcionan. Que ffmpeg liste `h264_nvenc` no garantiza que haya driver, GPU
libre o sesiones de codificación disponibles. Si pides `h264_nvenc` explícitamente y no
sirve, falla en vez de caer en silencio a CPU: pediste GPU por algo.

Medido en una RTX 5080: 5 clips de ~40 s renderizados en 19 s.

### Encuadre

Muchos vídeos traen barras negras **quemadas en la imagen**. Sin detectarlas, el clip
vertical las hereda y se come una cuarta parte del marco. `letterbox.py` muestrea 120
fotogramas con `cropdetect`, se queda con la propuesta más repetida y la descarta si sugiere
recortar más de la mitad del área — ante la duda, no recortar. El recorte 9:16 se calcula
después *dentro* de esa ventana de contenido.

Dentro de esa ventana, dónde cae el recorte 9:16 lo decide `framing.py` **por clip**, no
por proyecto: el sujeto está en un sitio distinto en cada momento del vídeo.

La pregunta que se responde no es *dónde está el punto medio del sujeto* sino **qué franja
vertical concentra más de lo que importa**. La diferencia no es sutil: con dos personas en
los extremos del plano, el punto medio cae entre las dos y la ventana no coge a ninguna.

Se construye un perfil de importancia por columnas, sumando:

| Señal | Peso | Cuándo manda |
|---|---:|---|
| Caras (Haar frontal + perfil) | 4 | Contenido hablado; si hay cara reconocible, gana |
| Movimiento entre fotogramas | 1 | Planos generales, gente de espaldas, cámara lejos |

Sobre ese perfil, una suma deslizante resuelta con la suma acumulada encuentra la posición
con más peso. Si el perfil sale plano —menos de un 8 % de diferencia entre la mejor franja y
la peor— se centra: inventarse una decisión sería peor que no tomarla.

El análisis cuesta unos **2 segundos por clip**: fotogramas en gris a 480 px, dos por
segundo, sacados de ffmpeg por una tubería. Medido sobre material real:

```
podcast, plano de un invitado descentrado    x 656 → 896   (+240 px, 80/80 caras)
comedia, plano general con acción a un lado  x 656 → 300   (−356 px, sin caras)
podcast, plano ya centrado                   x 656 → 644   (−12 px)
```

Cuando se equivoca, se corrige a mano. En el editor, al seleccionar un clip
aparece sobre el reproductor el rectángulo 9:16 que va a sobrevivir, con lo que
se pierde atenuado a los lados; se arrastra y ya está. Esa corrección se guarda
en `clip_candidates.crop_x` y **gana siempre**: el encuadre automático no se
vuelve a calcular para ese clip, porque recalcularlo desharía el trabajo del
usuario delante de sus narices. El botón «Volver al automático» limpia la
columna y devuelve la decisión a la máquina.

El encuadre con el que se generó cada fichero se guarda en `generated_clips`,
que es lo que permite pintar el rectángulo sin rehacer el análisis solo para
dibujarlo.

Con `SMART_CROP_PAN=true` la ventana además **sigue** al sujeto: se interpolan hasta doce
keyframes en una expresión del filtro `crop` de ffmpeg, que la evalúa en cada fotograma. Va
desactivado por defecto porque una cámara que se mueve sola no le sienta bien a todo el
material, no porque no funcione.

### Subtítulos

Se generan dos ficheros por clip: un `.srt` como sidecar descargable y un `.ass` que es el
que se incrusta. Los tiempos salen de los `TranscriptSegment` recortados a la ventana del
clip y desplazados a cero; los segmentos largos se parten en varias cues proporcionales al
tiempo, porque un segmento de Whisper de 12 segundos metido en dos líneas tapa media pantalla.

El `.ass` no es un capricho de formato. Un `.srt` solo puede estilarse con `force_style`, y
ahí libass interpreta los tamaños y márgenes sobre un lienzo de 384x288 en lugar de sobre el
vídeo real: `MarginV=380` se sale de la pantalla y el subtítulo simplemente no aparece.
`original_size` **no** arregla esto. Un `.ass` declara su propia `PlayResX/PlayResY`, así que
cada valor del estilo es un píxel del clip final.

```
BURN_SUBTITLES=true          # false deja el clip limpio; el .srt se genera igual
```

### Audio

Dos tratamientos que no se ven pero se notan al publicar.

**Volumen.** Medido con `ebur128` sobre tres vídeos de YouTube, los mismos
tramos sin tratar daban −12,5, −13,7 y −19,8 LUFS: **siete decibelios** entre el
más fuerte y el más flojo. Las plataformas normalizan al reproducir, pero lo
hacen *bajando* el que se pasa, así que un clip flojo se queda flojo.
`loudnorm` deja todos en −14 LUFS con un techo de pico que evita el recorte al
pasar a AAC.

**Entrada y salida.** Cortar en seco a mitad de una forma de onda produce un
chasquido audible. 80 ms de entrada lo eliminan sin que se perciba como fundido;
la salida es más larga porque un corte brusco al final se oye como un fallo de
reproducción. El vídeo **no** se funde a negro: los primeros fotogramas son
justo donde se decide si alguien sigue mirando.

```
AUDIO_NORMALIZE=true
AUDIO_TARGET_LUFS=-14
AUDIO_FADE_IN_SECONDS=0.08
AUDIO_FADE_OUT_SECONDS=0.35
```

### Gancho en pantalla

El mismo `.ass` lleva una segunda capa: el **gancho**, arriba y solo los primeros segundos.

No es decoración. Un clip del perfil visual no lleva subtítulos —no hay nada que
subtitular— así que sin esto se publica un vídeo mudo y sin una sola palabra que explique
qué se está mirando. El gancho es lo que decide si alguien deja de bajar el dedo.

Va arriba por dos motivos: no pisa a los subtítulos, y la mitad inferior la tapan el nombre
del autor, los botones y la barra de progreso de las tres aplicaciones.

Lo escribe la IA junto al resto del candidato, y se puede reescribir clip a clip desde el
editor: en la lista de clips, «En pantalla» es un campo editable. Vaciarlo quita el texto.

Un gancho largo se parte en líneas de `HOOK_LINE_LENGTH` caracteres y, si aun así no cabe,
se **recorta** con puntos suspensivos en lugar de encogerse: el tamaño está elegido para
leerse en un móvil a un brazo de distancia, y reducirlo para que quepa todo anula el motivo
de ponerlo.

```
HOOK_OVERLAY=true
HOOK_OVERLAY_SECONDS=3       # la ventana en la que se decide el scroll
HOOK_FONT_SIZE=100           # ~5 % de la altura de un 1080x1920
HOOK_LINE_LENGTH=18
```

## 12. Ingesta: los vídeos vienen solos

Durante once fases el sistema esperó a que alguien pegase una URL. Esta es la mitad
que faltaba: buscar desde dentro y vigilar canales.

**Nada de esto usa la API de datos de YouTube.** Ni clave, ni proyecto en Google
Cloud, ni cuota que se agota a las cien búsquedas. Las dos piezas ya estaban:

| | Cómo | Medido |
|---|---|---|
| Buscar | `yt-dlp` con `ytsearchN:`, en extracción plana | 1,3 s para 8 resultados |
| Vigilar un canal | El RSS público del canal (`feeds/videos.xml`) | 0,3 s, 15 vídeos |

La búsqueda devuelve título, canal, **duración y vistas** sin bajar un solo byte de
vídeo, que es lo que permite filtrar **antes** de descargar. Bajar 400 MB para
descubrir que el vídeo duraba tres horas o tenía doscientas visitas es el gasto más
tonto del pipeline.

### Canales vigilados

Un canal dado de alta convierte la aplicación en algo que corre solo: `celery beat`
dispara `clipforge.ingest.poll_channels` cada `INGEST_INTERVAL_MINUTES`, y lo que
sea nuevo entra en la cola sin que nadie toque nada.

Tres decisiones gobiernan la revisión:

- **La marca de agua se fija al dar de alta**, con la fecha del último vídeo del
  canal. Vigilar un canal es querer lo que publique *a partir de ahora*; sin esto,
  la primera revisión encolaría los quince vídeos que trae el feed.
- **La marca de agua avanza con todo lo visto, no solo con lo aceptado.** Si no, un
  vídeo descartado por el filtro se volvería a mirar en cada revisión, para siempre.
- **Un canal que falla no para a los demás.** El error se guarda en su fila —y se
  pinta en la interfaz— porque un canal callado tres días y uno roto tres días se
  ven exactamente igual sin eso.

Además, `INGEST_MAX_PER_CHECK` limita cuántos vídeos puede encolar un canal de una
vez: uno que publica quince de golpe no debe convertirse en quince descargas
simultáneas. Y ninguna URL que ya tenga proyecto se vuelve a encolar, porque el
feed repite los mismos quince vídeos en cada lectura.

### El temporizador va en su propio proceso

`celery beat` **no puede ir embebido en el worker** (`-B`) en Windows: Celery lo
rechaza al arrancar con *"-B option does not work on Windows"*. `start-dev.ps1` abre
una cuarta ventana para él. Sin esa ventana los canales siguen dados de alta pero
nadie los mira, y los vídeos solo entran con el botón «Revisar».

## 13. Publicar, y comprobar si acertamos

El último tramo manual era subir: abrir la carpeta y pegar título, descripción y
etiquetas cinco veces por proyecto. El botón **Subir a YouTube** de cada clip lo
hace con el texto ya puesto.

### El muro, por delante

**La API de datos de YouTube restringe a privado todo lo que sube un proyecto de
Google Cloud que no ha pasado su auditoría de cumplimiento.** El vídeo sube y queda
en el canal con su título y su descripción, pero hay que entrar a publicarlo.

Por eso `YOUTUBE_PRIVACY` viene en `private` de fábrica: es lo que va a pasar de
todos modos, y que la interfaz prometiera otra cosa sería mentir. La etiqueta
«privado» junto a cada clip subido está por lo mismo — creer que algo está publicado
cuando no lo está es peor que no haberlo subido. Con la auditoría aprobada se cambia
a `public` y ya está.

Aun con esa limitación lo que ahorra es real: el fichero, el título, la descripción
con su crédito y las etiquetas viajan solos y colocados.

### Autorizar, una vez

Autorizar abre el navegador y espera a que una persona diga que sí. Eso no lo puede
hacer un worker ni un endpoint, así que vive en un comando aparte:

```powershell
cd apps\backend
.\.venv\Scripts\pip.exe install -e .[publish]
.\.venv\Scripts\python.exe -m clipforge.services.publish.authorize
```

A partir de ahí queda un token que se refresca solo. El permiso pedido es
`youtube.upload` y nada más: este código sube, no husmea el canal.

### El bucle que faltaba

Y esto importa más de lo que parece. El sistema lleva cinco fases afinando una
rúbrica de siete dimensiones **sin que ningún clip publicado le haya dicho nunca si
acierta**. Con el id del vídeo subido se cierra el círculo: cada doce horas
`clipforge.publish.refresh_stats` relee las vistas de lo publicado en el último mes
y las guarda junto al clip, al lado de su nota.

Las vistas se leen con **yt-dlp, no con la API de analíticas**: son públicas, así que
no hacen falta credenciales ni se gasta cuota. Es menos preciso que el panel de
YouTube —no hay retención ni impresiones— pero responde a la única pregunta que se
estaba haciendo: de estos cinco clips, ¿cuál funcionó?

## 14. Vídeos que no hablan

El análisis de la sección anterior solo lee texto, y hay vídeos que no lo tienen. Sobre una
recopilación de comedia física de 8:39, Whisper detectó "coreano" con un 47 % de confianza y
produjo **tres segmentos y quince caracteres** — ninguno era habla real. El analizador no
podía devolver otra cosa que una lista vacía, y el proyecto acababa en `FAILED` tras
descargar 379 MB.

Ahora el pipeline mide tres señales que no dependen del idioma:

| Señal | Cómo | Qué marca |
|---|---|---|
| Volumen | `astats` sobre el WAV, RMS cada 0,5 s | Golpes, caídas, risas, acentos musicales |
| Cortes de plano | `select='gt(scene,0.35)'` a 320 px | Dónde empieza y acaba cada sketch |
| Movimiento | `tblend=difference` + `signalstats` a 4 fps | Acción física |

Sobre ese mismo vídeo, 35 segundos de ffmpeg: 30 picos de sonido, 36 cortes y 20 tramos
publicables donde el texto daba cero. Se guardan como JSONB en `projects.signals` (unos
50 kB) y los consumen tanto el análisis como la línea de tiempo del editor.

### Perfil de contenido

Tras transcribir se calcula la fracción del vídeo con habla real. Con menos de
`VISUAL_SPEECH_RATIO` (o menos de `VISUAL_CHARS_PER_MINUTE` caracteres por minuto) el
proyecto pasa al perfil **visual**, que cambia tres cosas:

- **Rúbrica.** `setup` 20, `payoff` 25, `reaction` 15, `universality` 15, `pacing` 15,
  `duration` 10. No pide citas textuales ni premia "enseñar algo", que es lo que dejaba a
  un gag visual con cero en la mitad del baremo.
- **Duraciones.** 10–60 s con óptimo en 25, en lugar de 20–90 con óptimo en 45.
- **Subtítulos.** No se incrustan: no hay nada que subtitular.

Las siete columnas de puntuación de `clip_candidates` no cambian; lo que cambia es qué
dimensión guarda cada una. Así se puede añadir una rúbrica sin migrar la base de datos.

### Análisis visual

Con perfil visual, de cada bloque se extraen `VISION_FRAMES_PER_BLOCK` fotogramas a 512 px
y se le enseñan a un modelo multimodal, **de uno en uno**: con tres bloques en la misma
petición un modelo local de 7B deja de distinguirlos y devuelve el mismo título para los
tres. Se mantiene la regla de siempre — el modelo elige un bloque, el backend calcula los
tiempos.

Sobre el vídeo de referencia, con `qwen2.5vl:7b` en local: 15 peticiones, dos minutos, y
clips titulados «El agricultor se desliza en el barro» (95/100) o «El salto del niño».
Para calidad de verdad, `AI_VISION_PROVIDER=anthropic` con `claude-opus-5`.

### Nunca terminar con las manos vacías

Si el análisis no propone nada —o el proveedor falla— el proyecto **no** se marca como
fallido. Se guardan los mejores bloques como candidatos `SIGNAL` sin puntuar, el estado
pasa a `NEEDS_REVIEW` y el vídeo original se conserva pase lo que pase con
`KEEP_SOURCE_VIDEO`. El editor manual hace el resto.

## 15. Editor manual

`/projects/{id}` abre el vídeo original con la línea de tiempo de señales debajo, en cinco
carriles sobre el mismo eje: volumen, movimiento, cortes, tramos propuestos y clips ya
definidos. Un clic en un tramo ajusta entrada y salida a él, que es lo que convierte diez
minutos de arrastrar la cabeza lectora en un clic.

Atajos de montador: `espacio` reproducir, `I` y `O` marcar entrada y salida, `J K L`
lanzadera, flechas ±1 s y `shift`+flechas fotograma a fotograma.

Cada clip se renderiza por separado con la tarea `clipforge.pipeline.render_candidate`, que
comparte el código de render con el pipeline: un clip manual y uno de la IA son el mismo
fichero con el mismo encuadre.

Los límites de duración del perfil **no** se aplican a un recorte manual: son una guía para
el modelo, no una regla para la persona que está mirando el vídeo. Y un reprocesado
sustituye lo que produjo la máquina (`AI` y `SIGNAL`) pero nunca borra un candidato
`MANUAL`.

## 16. Almacenamiento

```
storage/projects/{project_id}/
├─ source/        vídeo original      (KEEP_SOURCE_VIDEO, por defecto se conserva)
├─ audio/         WAV 16 kHz mono     (KEEP_AUDIO, se borra tras transcribir)
├─ transcripts/   transcripciones
├─ clips/         clips finales       (siempre se conservan)
├─ subtitles/     .srt / .ass
└─ temp/          intermedios         (siempre se borran)
```

### Carpeta para subir los clips

Los nombres de arriba son opacos a propósito: estables, independientes de lo que
devuelva un LLM y sin colisiones. Pero nadie quiere subir `clip_01_9cd4a39e.mp4` a
TikTok sin saber cuál es. Al terminar el render se deja una segunda vista:

```
storage/export/{título del vídeo}/
├─ 01 - El negocio de la muerte - ¿Cuánto vale.mp4
├─ 01 - El negocio de la muerte - ¿Cuánto vale.srt
├─ 01 - El negocio de la muerte - ¿Cuánto vale.txt   ← lo que se pega en YouTube
├─ 02 - El mejor currículum es hacer el trabajo antes de ser contratado.mp4
├─ ...
└─ youtube.csv                                        ← todos, para subir en tanda
```

Ordenados por ranking y con tildes y espacios, que es lo que hace que la carpeta
sirva de algo. Se quitan solo los caracteres que Windows prohíbe (`<>:"/\|?*`),
los de control, los puntos y espacios finales —que Windows recorta en silencio— y
los nombres de dispositivo heredados de MS-DOS (`CON`, `NUL`, `COM1`…), que no se
pueden usar ni con extensión.

**No ocupa el doble de disco.** Se crean enlaces duros, que son otro nombre para
los mismos bytes; solo se copia si el sistema de ficheros no los admite (FAT, un
recurso de red, otro volumen). Exportar 15 clips cuesta 0 bytes.

Es una **vista derivada**: se puede borrar entera sin perder nada y se reconstruye
en cada render. Un reproceso la vacía antes de rellenarla, para que no queden
clips viejos haciéndose pasar por buenos. Una carpeta sin la marca
`.clipforge-project` no se toca nunca, por si `EXPORT_PATH` apunta a un sitio con
otras cosas dentro.

```
# EXPORT_PATH=            # por defecto <STORAGE_PATH>/export; admite ruta absoluta
EXPORT_CLIPS=true         # false desactiva la exportación
```

Las rutas relativas se anclan a la raíz del repositorio, no al directorio desde el
que arrancas: uvicorn, celery, pytest y alembic se lanzan desde sitios distintos.

En base de datos se guardan **rutas relativas** a `STORAGE_PATH`, de modo que mover la carpeta o
migrar a S3/R2 no invalida los registros existentes.

## 17. Migraciones

```powershell
cd apps\backend
.\.venv\Scripts\alembic.exe revision --autogenerate -m "descripcion"
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe downgrade -1
```

Revisa siempre el fichero generado antes de aplicarlo.

## 18. Hoja de ruta

- [x] **FASE 1** — infraestructura, API, BD, worker, frontend
- [x] **FASE 2** — descarga con yt-dlp y creación de proyectos
- [x] **FASE 3** — transcripción con faster-whisper sobre CUDA
- [x] **FASE 4** — análisis de viralidad con LLM
- [x] **FASE 5** — recorte y render vertical con FFmpeg/NVENC
- [x] **FASE 6** — el análisis vacío ya no tira el proyecto: `NEEDS_REVIEW`
- [x] **FASE 7** — señales no verbales (volumen, cortes de plano, movimiento)
- [x] **FASE 8** — perfiles de contenido con rúbrica y duraciones propias
- [x] **FASE 9** — análisis visual con modelo multimodal
- [x] **FASE 10** — Whisper con traducción y guarda contra alucinaciones
- [x] **FASE 11** — candidatos manuales y render de un clip suelto
- [x] **FASE 12** — editor con línea de tiempo de señales
- [x] **FASE 13** — encuadre inteligente por caras y movimiento
- [x] **FASE 14** — gancho en pantalla y audio igualado
- [x] **FASE 15** — encuadre corregible a mano
- [x] **FASE 16** — títulos en inglés, palabras clave, metadatos de publicación
- [x] **FASE 17** — ingesta: búsqueda en YouTube y canales vigilados
- [x] **FASE 18** — publicación en YouTube y lectura de vistas reales
