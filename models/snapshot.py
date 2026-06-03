"""
models/snapshot.py
==================
Modelos Pydantic para el Motor (Backend) del sistema EPIC Playground.

Responsabilidad única: validar estrictamente la entrada JSON, procesar la
lógica de Belnap y devolver el JSON modificado. El campo `visual` se
transporta opaco ("ceguera espacial"): el Motor nunca lo interpreta ni
lo modifica, solo lo reenvía intacto al front-end.

Lógica de cuatro valores (Belnap / FOUR):
  V → True      (solo verdadero)
  F → False     (solo falso)
  N → None      (ni verdadero ni falso – sin información)
  B → Both      (tanto verdadero como falso – sobre-determinado)
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 1. EvidentialValue — cuatro valores de la lógica de Belnap
# ---------------------------------------------------------------------------

class EvidentialValue(str, Enum):
    """
    Valores epistémicos del retículo de Belnap (FOUR).

    El orden parcial del retículo de conocimiento es:
        N < V, F < B
    (N = "sin información", B = "sobre-determinado")
    """

    TRUE          = "V"   # Verdadero (True)
    FALSE         = "F"   # Falso (False)
    NONE          = "N"   # Sin información (None / Unknown)
    BOTH          = "B"   # Sobre-determinado (Both / Contradictory)


# ---------------------------------------------------------------------------
# 2. Capa lógica
# ---------------------------------------------------------------------------

class LogicVariable(BaseModel):
    """
    Nodo del grafo: una variable proposicional con su valor evidencial actual.

    Atributos
    ----------
    id    : Identificador único de la variable (e.g. "p", "q", "x1").
    value : Valor epistémico actual según EvidentialValue.
    """

    id: str = Field(
        ...,
        min_length=1,
        description="Identificador único de la variable proposicional.",
        examples=["p", "q", "x1"],
    )
    value: EvidentialValue = Field(
        ...,
        description="Valor epistémico actual de la variable (V | F | N | B).",
    )


class LogicRelation(BaseModel):
    """
    Arista del grafo: una relación lógica dirigida entre dos variables.

    Atributos
    ----------
    id               : Identificador único de la relación.
    source           : `id` de la variable origen (antecedente).
    target           : `id` de la variable destino (consecuente).
    connective       : Conectivo lógico que define la relación
                       (e.g. "IMPLIES", "AND", "OR", "NOT", "BICONDITIONAL").
    is_contrapositive: Si True, la relación ya representa la contrapositiva
                       de otra relación base. Default False.
    """

    id: str = Field(
        ...,
        min_length=1,
        description="Identificador único de la relación.",
        examples=["r1", "r_pq"],
    )
    source: str = Field(
        ...,
        min_length=1,
        description="`id` de la variable origen (antecedente de la relación).",
    )
    target: str = Field(
        ...,
        min_length=1,
        description="`id` de la variable destino (consecuente de la relación).",
    )
    connective: str = Field(
        ...,
        min_length=1,
        description=(
            "Conectivo lógico de la relación "
            "(e.g. 'IMPLIES', 'AND', 'OR', 'NOT', 'BICONDITIONAL')."
        ),
        examples=["IMPLIES", "AND", "OR", "NOT", "BICONDITIONAL"],
    )
    is_contrapositive: bool = Field(
        default=False,
        description=(
            "Indica si esta relación es la contrapositiva de otra relación base. "
            "El Motor puede generar contrapositivas automáticamente durante la "
            "propagación; este flag las distingue de las relaciones originales."
        ),
    )


class LogicSet(BaseModel):
    """
    Conjunto de variables y relaciones que forman el espacio lógico.

    Atributos
    ----------
    variables : Lista de todas las variables proposicionales del grafo.
    relations : Lista de todas las relaciones (aristas) del grafo.
    """

    variables: List[LogicVariable] = Field(
        default_factory=list,
        description="Lista de variables proposicionales del grafo lógico.",
    )
    relations: List[LogicRelation] = Field(
        default_factory=list,
        description="Lista de relaciones (aristas dirigidas) del grafo lógico.",
    )


class LogicGraph(BaseModel):
    """
    Grafo lógico completo: agrupa el conjunto lógico bajo una raíz semántica.

    Atributos
    ----------
    logic_set : El conjunto de variables y relaciones del playground.
    """

    logic_set: LogicSet = Field(
        default_factory=LogicSet,
        description="Conjunto lógico: variables y relaciones del playground.",
    )


# ---------------------------------------------------------------------------
# 3. Rastro de ejecución (Execution Trace)
# ---------------------------------------------------------------------------

class ExecutionAction(BaseModel):
    """
    Acción atómica registrada durante un paso de propagación del Motor.

    Cada vez que el Motor modifica el valor de una variable, genera una
    `ExecutionAction` que documenta el cambio con contexto suficiente para
    reproducir o auditar la propagación.

    Atributos
    ----------
    step          : Número de paso global dentro de la ejecución (≥ 0).
    variable_id   : `id` de la variable afectada por este paso.
    old_value     : Valor epistémico antes del cambio.
    new_value     : Valor epistémico después del cambio.
    description   : Explicación legible del motivo del cambio
                    (e.g. "Propagación via relación r1: IMPLIES V → V").
    is_stabilized : True si tras este paso el grafo alcanzó punto fijo
                    (ninguna variable cambiaría en la siguiente iteración).
    """

    step: int = Field(
        ...,
        ge=0,
        description="Número de paso global dentro de la ejecución (≥ 0).",
    )
    variable_id: str = Field(
        ...,
        min_length=1,
        description="`id` de la variable proposicional afectada.",
    )
    old_value: EvidentialValue = Field(
        ...,
        description="Valor epistémico de la variable antes del cambio.",
    )
    new_value: EvidentialValue = Field(
        ...,
        description="Valor epistémico de la variable después del cambio.",
    )
    description: str = Field(
        ...,
        min_length=1,
        description=(
            "Explicación legible del motivo del cambio. "
            "Útil para la UI de depuración paso a paso."
        ),
        examples=["Propagación via relación r1 (IMPLIES): V → V"],
    )
    is_stabilized: bool = Field(
        ...,
        description=(
            "True si, tras aplicar este cambio, el grafo alcanzó punto fijo "
            "(ningún valor cambiaría en la siguiente iteración)."
        ),
    )


class ExecutionTrace(BaseModel):
    """
    Rastro completo de la ejecución del Motor para un snapshot dado.

    El Motor genera y adjunta este objeto al `PlaygroundSnapshot` de respuesta.
    El front-end lo usa para animar la propagación paso a paso.

    Atributos
    ----------
    actions          : Lista ordenada de acciones atómicas ejecutadas.
    stabilized       : True si la propagación convergió a punto fijo.
    total_iterations : Número total de iteraciones de propagación realizadas.
    """

    actions: List[ExecutionAction] = Field(
        default_factory=list,
        description="Lista ordenada de acciones atómicas de la propagación.",
    )
    stabilized: bool = Field(
        ...,
        description=(
            "True si la propagación terminó por convergencia (punto fijo). "
            "False si se detuvo por alcanzar `max_iterations`."
        ),
    )
    total_iterations: int = Field(
        ...,
        ge=0,
        description="Número total de iteraciones de propagación realizadas.",
    )


# ---------------------------------------------------------------------------
# 4. Metadatos del Playground
# ---------------------------------------------------------------------------

class PlaygroundMeta(BaseModel):
    """
    Metadatos de configuración del Playground para la sesión actual.

    Atributos
    ----------
    max_iterations : Límite de iteraciones del Motor antes de forzar parada.
                     Protege contra ciclos infinitos en grafos con retroalimentación.
                     Default: 100.
    """

    max_iterations: int = Field(
        default=100,
        ge=1,
        description=(
            "Número máximo de iteraciones de propagación permitidas. "
            "El Motor se detiene (con `stabilized=False`) si lo alcanza. "
            "Default: 100."
        ),
    )


# ---------------------------------------------------------------------------
# 5. PlaygroundSnapshot — modelo raíz
# ---------------------------------------------------------------------------

class PlaygroundSnapshot(BaseModel):
    """
    Modelo raíz del Motor EPIC Playground.

    Representa tanto la **entrada** (petición del front-end) como la
    **salida** (respuesta enriquecida del Motor). El ciclo de vida es:

        Front-end  →  POST /run  →  Motor (valida con este modelo)
                                    Motor procesa lógica
                                    Motor completa `execution_trace`
                   ←  200 OK    ←  Motor serializa este modelo

    Campos
    ------
    meta            : Configuración de la sesión (max_iterations, etc.).
    logic           : Grafo lógico con variables y relaciones a procesar.
    execution_trace : Rastro generado por el Motor. None en la petición
                      de entrada; poblado en la respuesta de salida.
    visual          : Datos espaciales/visuales del front-end.
                      **El Motor los ignora completamente y los reenvía
                      intactos ("ceguera espacial").** Acepta cualquier
                      estructura de diccionario sin validación adicional.
    """

    meta: PlaygroundMeta = Field(
        default_factory=PlaygroundMeta,
        description="Metadatos de configuración de la sesión del Playground.",
    )
    logic: LogicGraph = Field(
        default_factory=LogicGraph,
        description="Grafo lógico (variables + relaciones) a procesar por el Motor.",
    )
    execution_trace: Optional[ExecutionTrace] = Field(
        default=None,
        description=(
            "Rastro de ejecución generado por el Motor. "
            "Es None en las peticiones de entrada y se puebla en la respuesta."
        ),
    )
    visual: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Datos visuales/espaciales del front-end (posiciones de nodos, "
            "estilos, viewport, etc.). "
            "El Motor tiene 'ceguera espacial': este campo se acepta tal cual, "
            "nunca se interpreta ni se modifica, y se reenvía intacto al front-end."
        ),
    )

    model_config = {
        # Permite serializar Enums como su valor string (e.g. "V", "F", "N", "B")
        "use_enum_values": True,
        # Documenta el schema JSON con los Field(...) descriptivos
        "populate_by_name": True,
    }
