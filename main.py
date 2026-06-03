"""
main.py
=======
Punto de entrada del microservicio Motor EPIC Playground.

Responsabilidad
---------------
Instanciar y configurar la aplicación FastAPI:
  - Registrar el middleware de CORS (crítico para el Editor en otro origen).
  - Montar el router del Motor (`api/routes.py`).
  - Exponer un endpoint de health check en GET /.

Arranque
--------
Desarrollo (con recarga automática):
    uvicorn main:app --reload --port 8000

Producción:
    uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4

Documentación interactiva generada automáticamente por FastAPI:
    http://localhost:8000/docs     (Swagger UI)
    http://localhost:8000/redoc    (ReDoc)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router as motor_router

# ---------------------------------------------------------------------------
# Instancia de la aplicación
# ---------------------------------------------------------------------------

app = FastAPI(
    title="EPIC Playground Motor API",
    description=(
        "Motor de propagación lógica basado en la lógica de cuatro valores de "
        "Belnap (FOUR). Recibe un grafo de variables y relaciones, ejecuta el "
        "ciclo de propagación monotónica en el retículo de información (≤_k) y "
        "devuelve el snapshot enriquecido con los valores effectivos finales y "
        "el rastro de ejecución paso a paso.\n\n"
        "Diseñado para ser consumido por el Editor EPIC Playground "
        "(aplicación React en un origen distinto)."
    ),
    version="1.0.0",
    contact={
        "name": "EPIC Playground — Equipo de Desarrollo",
    },
    license_info={
        "name": "MIT",
    },
)

# ---------------------------------------------------------------------------
# Middleware CORS
#
# CRÍTICO: el Editor corre en un origen diferente (e.g. http://localhost:5173
# con Vite) y el navegador bloquearía las peticiones sin estos headers.
# allow_origins=["*"] es adecuado para desarrollo y para un API pública de
# lógica que no maneja autenticación ni datos sensibles de usuario.
# En un entorno de producción con autenticación, reemplazar "*" por la lista
# explícita de orígenes permitidos (e.g. ["https://epic-playground.app"]).
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # Permite cualquier origen (Editor en cualquier puerto)
    allow_credentials=True,    # Necesario si en el futuro se añaden cookies/auth
    allow_methods=["*"],       # GET, POST, OPTIONS, etc.
    allow_headers=["*"],       # Content-Type, Authorization, etc.
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(motor_router)

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get(
    "/",
    tags=["Sistema"],
    summary="Health check",
    description="Verifica que el Motor está en línea y listo para recibir peticiones.",
    response_description="Estado operacional del servicio.",
)
async def health_check() -> dict:
    """
    Endpoint de verificación de estado.

    Útil para:
    - Balanceadores de carga (load balancers) que necesitan confirmar que la
      instancia está viva antes de enrutar tráfico hacia ella.
    - Scripts de CI/CD que esperan a que el servicio arranque.
    - El propio Editor, que puede consultar este endpoint al iniciar para
      confirmar que el Motor está disponible.

    Returns
    -------
    dict
        ``{"status": "online", "motor": "EPIC Playground Motor API", "version": "1.0.0"}``
    """
    return {
        "status": "online",
        "motor": app.title,
        "version": app.version,
    }
