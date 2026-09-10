"""Autorización única de YouTube, desde la línea de comandos.

Vive aparte del resto a propósito. Autorizar abre el navegador y espera a que
una persona diga que sí; eso no lo puede hacer un worker ni un endpoint, y
meterlo en el arranque dejaría la aplicación colgada esperando un clic que
nadie va a dar.

Se ejecuta **una vez**:

    cd apps/backend
    .\\.venv\\Scripts\\python.exe -m clipforge.services.publish.authorize

A partir de ahí queda un token en `YOUTUBE_TOKEN_FILE` que se refresca solo.

Antes hace falta un `client_secrets.json` de un proyecto de Google Cloud con la
API de datos de YouTube activada, y credenciales de tipo *aplicación de
escritorio*. Ese fichero es secreto: va fuera del repositorio.
"""

from __future__ import annotations

import sys
from pathlib import Path

from clipforge.core.config import settings
from clipforge.services.publish.youtube import SCOPES


def main() -> int:
    """Pide autorización en el navegador y guarda el token."""
    secrets = settings.youtube_client_secrets_file
    token_file = settings.youtube_token_file

    if not secrets or not Path(secrets).is_file():
        print(
            "Falta el fichero de credenciales.\n\n"
            "1. Crea un proyecto en https://console.cloud.google.com\n"
            "2. Activa 'YouTube Data API v3'\n"
            "3. Credenciales -> Crear -> ID de cliente de OAuth -> Aplicación de escritorio\n"
            "4. Descarga el JSON y apunta YOUTUBE_CLIENT_SECRETS_FILE a él en el .env\n",
            file=sys.stderr,
        )
        return 1

    if not token_file:
        print("Falta YOUTUBE_TOKEN_FILE en el .env", file=sys.stderr)
        return 1

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print(
            "Faltan las librerías de Google. Instálalas con: pip install -e .[publish]",
            file=sys.stderr,
        )
        return 1

    flow = InstalledAppFlow.from_client_secrets_file(str(secrets), SCOPES)
    # Puerto 0: que el sistema elija uno libre. Fijarlo choca con cualquier
    # cosa que ya esté escuchando y el error que sale no lo explica.
    credentials = flow.run_local_server(port=0, prompt="consent")

    destination = Path(token_file)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(credentials.to_json(), encoding="utf-8")

    print(f"Autorización guardada en {destination}")
    print("Ya puedes publicar clips desde la aplicación.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
