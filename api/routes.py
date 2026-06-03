"""
api/routes.py
=============
Router FastAPI del Motor EPIC Playground.

Responsabilidad única
---------------------
Actuar como la interfaz HTTP del Motor: deserializar la petición JSON en
un `PlaygroundSnapshot` validado por Pydantic, delegar el procesamiento a
`run_propagation` y serializar el resultado de vuelta a JSON.

Este módulo NO contiene lógica de negocio. Toda la matemática vive en
`core/` y toda la orquestación en `services/engine.py`.

Endpoints
---------
POST /calcular
    Recibe un PlaygroundSnapshot (entrada del Editor),
    ejecuta el ciclo de propagación Belnap y devuelve el snapshot
    enriquecido con el ExecutionTrace y los valores efectivos finales.
"""

from fastapi import APIRouter, HTTPException, status

from models.snapshot import PlaygroundSnapshot
from services.engine import run_propagation

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/calcular",
    tags=["Motor"],
)

# ---------------------------------------------------------------------------
# POST /calcular
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=PlaygroundSnapshot,
    status_code=status.HTTP_200_OK,
    summary="Ejecutar propagación Belnap",
    description=(
        "Recibe el estado actual del playground (variables, relaciones y datos "
        "visuales), ejecuta el ciclo de propagación monotónica en el retículo de "
        "Belnap (FOUR) y devuelve el snapshot enriquecido con los valores "
        "effectivos finales y el rastro de ejecución paso a paso.\n\n"
        "El campo `visual` se reenvía intacto sin ser interpretado por el Motor "
        "(principio de ceguera espacial)."
    ),
    response_description=(
        "Snapshot procesado: valores effectivos actualizados en "
        "`logic.logic_set.variables` y rastro completo en `execution_trace`."
    ),
)
async def calcular(snapshot: PlaygroundSnapshot) -> PlaygroundSnapshot:
    """
    Punto de entrada principal del Motor EPIC Playground.

    Parameters
    ----------
    snapshot : PlaygroundSnapshot
        Estado del playground enviado por el Editor. Pydantic valida
        automáticamente la estructura antes de que este handler sea invocado.
        Si el JSON es inválido, FastAPI responde con 422 Unprocessable Entity
        sin llegar aquí.

    Returns
    -------
    PlaygroundSnapshot
        El mismo snapshot mutado in-place con:
        - `logic.logic_set.variables[*].value` actualizados al effective final.
        - `execution_trace` poblado con todas las acciones y el flag de
          estabilización.
        - `visual` intacto (ceguera espacial).

    Raises
    ------
    HTTPException (500)
        Solo si ocurre un error interno inesperado en el Motor. Los errores
        de validación de entrada (JSON malformado, valores fuera de FOUR) son
        manejados por FastAPI/Pydantic y retornan 422 automáticamente.
    """
    try:
        resultado = run_propagation(snapshot)
    except Exception as exc:
        # Cualquier excepción no anticipada del Motor se captura aquí para
        # devolver un 500 controlado en lugar de un traceback crudo.
        # En producción, este bloque debería también registrar el error en
        # un sistema de logging estructurado (e.g. structlog, loguru).
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno del Motor durante la propagación: {exc}",
        ) from exc

    return resultado
