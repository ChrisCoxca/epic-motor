"""
services/engine.py
==================
Servicio principal del Motor EPIC Playground.

Responsabilidad
---------------
Actúa como el único puente entre la capa de contratos Pydantic
(`models/snapshot.py`) y el núcleo matemático puro (`core/`).
No contiene lógica matemática propia: orquesta, inicializa, itera
y registra. Todo el razonamiento evidencial vive en `core/`.

Flujo de ejecución
------------------

    PlaygroundSnapshot (entrada)
          │
          ▼
    [1] Inicialización de estados
        • Lee snapshot.logic.variables
        • Crea un VariableState por variable
        • restrict() inicial al valor declarado en el JSON
          │
          ▼
    [2] Inicialización de relaciones
        • Lee snapshot.logic.relations
        • Por cada relación crea z_virtual (la relación "es verdadera")
        • Construye ImplicationMatrix(p, q, z_virtual)
          │
          ▼
    [3] Bucle de estabilización (máx. max_iterations)
        • Snapshot de effectivos antes del barrido
        • Barrido: evaluate() en todas las matrices
        • Diff: por cada variable que mutó → ExecutionAction
        • ¿Ninguna mutación? → punto fijo → break
          │
          ▼
    [4] Finalización
        • Escribe effective finales en snapshot.logic.variables
        • Inyecta ExecutionTrace en snapshot.execution_trace
        • Retorna el snapshot modificado (mismo objeto)

Garantías
---------
• Monotonía: ningún valor puede "subir" en el retículo una vez fijado.
• Terminación: el bucle se rompe en ≤ max_iterations iteraciones,
  ya que el conjunto admisible solo puede reducirse (máx. 4 veces por
  variable) y el número de variables es finito.
• Trazabilidad: cada mutación queda registrada en ExecutionAction con
  step, variable_id, old_value, new_value y description.
• Ceguera espacial: el campo `visual` del snapshot nunca se toca.
"""

from __future__ import annotations

from typing import Dict, List

from core.belnap import VariableState
from core.connectives import ImplicationMatrix
from models.snapshot import (
    EvidentialValue,
    ExecutionAction,
    ExecutionTrace,
    PlaygroundSnapshot,
)

# ---------------------------------------------------------------------------
# Constante: valor que se le asigna a z_virtual
# Una relación dibujada en el editor = afirmación de que el conectivo es V
# (al menos parcialmente verdadero → restrict a {"V", "B"})
# ---------------------------------------------------------------------------
_Z_POSITIVE: set[str] = {"V", "B"}

# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _snapshot_effective(states: Dict[str, VariableState]) -> Dict[str, str]:
    """
    Devuelve una copia inmutable del valor `effective` de cada variable.

    Se llama al inicio de cada iteración del bucle para poder comparar
    antes/después del barrido de matrices y detectar mutaciones.

    Parameters
    ----------
    states : Mapping id → VariableState

    Returns
    -------
    Dict[str, str]
        {variable_id: effective_actual}
    """
    return {var_id: state.effective for var_id, state in states.items()}


def _build_description(
    var_id: str,
    old_value: str,
    new_value: str,
    iteration: int,
) -> str:
    """
    Genera la descripción legible de una mutación para el ExecutionAction.

    Parameters
    ----------
    var_id    : Identificador de la variable que mutó.
    old_value : Valor effectivo antes de la iteración.
    new_value : Valor effectivo después de la iteración.
    iteration : Número de iteración del bucle de estabilización.

    Returns
    -------
    str
        Texto listo para poblar ExecutionAction.description.
    """
    return (
        f"[iter={iteration}] Variable '{var_id}': "
        f"{old_value!r} → {new_value!r} "
        f"(mutación por propagación monotónica en retículo ≤_k)"
    )


def _to_evidential(value: str) -> EvidentialValue:
    """
    Convierte un string "V"|"F"|"N"|"B" al enum EvidentialValue.

    La separación entre el núcleo matemático (strings puros) y los modelos
    Pydantic (EvidentialValue) se cierra aquí, en el servicio.

    Parameters
    ----------
    value : Uno de "V", "F", "N", "B".

    Returns
    -------
    EvidentialValue

    Raises
    ------
    KeyError
        Si el núcleo matemático devuelve un valor inesperado (bug interno).
    """
    _MAP: Dict[str, EvidentialValue] = {
        "V": EvidentialValue.TRUE,
        "F": EvidentialValue.FALSE,
        "N": EvidentialValue.NONE,
        "B": EvidentialValue.BOTH,
    }
    try:
        return _MAP[value]
    except KeyError:
        raise ValueError(
            f"El núcleo matemático devolvió un valor fuera del universo FOUR: {value!r}. "
            "Esto indica un bug en core/belnap.py."
        ) from None


# ---------------------------------------------------------------------------
# Función pública principal
# ---------------------------------------------------------------------------


def run_propagation(snapshot: PlaygroundSnapshot) -> PlaygroundSnapshot:
    """
    Ejecuta el ciclo completo de propagación Belnap sobre el snapshot.

    Recibe el snapshot validado por Pydantic, procesa la lógica usando el
    núcleo matemático puro y devuelve el mismo objeto enriquecido con:
      • Los valores `effective` finales en `snapshot.logic.variables`.
      • El rastro de ejecución completo en `snapshot.execution_trace`.

    El campo `snapshot.visual` nunca es leído ni modificado
    ("ceguera espacial" del Motor).

    Parameters
    ----------
    snapshot : PlaygroundSnapshot
        Snapshot validado por Pydantic. Puede tener `execution_trace=None`
        (estado normal de entrada desde el front-end).

    Returns
    -------
    PlaygroundSnapshot
        El mismo objeto `snapshot` mutado in-place y enriquecido.
        El front-end recibirá este objeto serializado como respuesta JSON.

    Notes
    -----
    La función muta `snapshot` in-place en lugar de construir una copia.
    Esto es correcto porque:
      a) Pydantic ya garantizó la validez de la entrada antes de llamar aquí.
      b) El Motor es stateless entre requests; cada llamada recibe su propio
         objeto snapshot.
      c) Evita duplicar una estructura potencialmente grande solo para la
         serialización de salida.
    """

    max_iterations: int = snapshot.meta.max_iterations
    actions: List[ExecutionAction] = []
    global_step: int = 0

    # ── [1] INICIALIZACIÓN DE ESTADOS ─────────────────────────────────────
    #
    # Creamos un VariableState por cada variable declarada en el JSON.
    # El VariableState arranca con admissible = FOUR completo (ignorancia total),
    # y luego hacemos restrict() al valor inicial declarado por el front-end.
    #
    # ¿Por qué restrict() en lugar de pasar el valor al constructor?
    # Porque queremos que la mecánica de conjuntos sea consistente desde el
    # primer ciclo. Si una variable llega con "V", su admissible queda como
    # {"V"}, y ninguna propagación hacia atrás podrá ampliarla (monotonía).
    # Esto modela la semántica correcta: el front-end "sabe" que p = V.

    states: Dict[str, VariableState] = {}

    for var in snapshot.logic.logic_set.variables:
        state = VariableState(initial_value=var.value)
        # Aplicamos restrict() inicial SOLO cuando el front-end declara evidencia
        # definitiva (V o F). En esos casos fijamos el admissible al conjunto de
        # valores compatibles con esa evidencia dentro del retículo:
        #
        #   "V" → la variable tiene evidencia de ser verdadera       → restrict({"V", "B"})
        #   "F" → la variable tiene evidencia de ser falsa            → restrict({"F", "B"})
        #   "N" → sin información: admissible permanece FOUR completo → sin restrict
        #   "B" → sobre-determinado: tiene ambas evidencias            → sin restrict
        #
        # No restringimos N ni B a sus singletons porque hacerlo cerraría el
        # conjunto admissible antes de que la propagación pueda aportar evidencia,
        # rompiendo la monotonía y produciendo colapsos vacíos (effective="B" por error).
        _INITIAL_RESTRICT: dict[str, set[str]] = {
            "V": {"V", "B"},   # al menos parcialmente verdadero
            "F": {"F", "B"},   # al menos parcialmente falso
            # "N" y "B" no restringen: FOUR permanece abierto
        }
        if var.value in _INITIAL_RESTRICT:
            state.restrict(_INITIAL_RESTRICT[var.value])
        states[var.id] = state

    # ── [2] INICIALIZACIÓN DE RELACIONES ──────────────────────────────────
    #
    # Cada relación en el editor es una AFIRMACIÓN de que el conectivo se
    # sostiene (es verdadero o sobre-determinado). La modelamos como una
    # variable virtual z_virtual con admissible restringido a {"V", "B"}
    # (evidencia positiva).
    #
    # Esto es lo que le da "peso" a la relación durante la propagación:
    # ImplicationMatrix leerá z.effective = "V" y habilitará UI+ y UI-.

    matrices: List[ImplicationMatrix] = []
    z_virtuals: List[VariableState] = []  # mantenemos referencias vivas

    for relation in snapshot.logic.logic_set.relations:
        # Obtener los estados de source y target; ignorar relaciones con
        # variables no declaradas (grafo malformado pero no fatal)
        p_state = states.get(relation.source)
        q_state = states.get(relation.target)

        if p_state is None or q_state is None:
            # Relación huérfana: source o target no existen en variables.
            # El Motor la ignora silenciosamente; el front-end ya debería
            # garantizar la coherencia del grafo, pero somos defensivos.
            continue

        # Variable virtual que representa "esta relación es verdadera"
        z_virtual = VariableState(initial_value="V")
        z_virtual.restrict(_Z_POSITIVE)  # fijar evidencia positiva
        z_virtuals.append(z_virtual)     # evitar que el GC la libere

        matrix = ImplicationMatrix(
            p=p_state,
            q=q_state,
            z=z_virtual,
            relation_id=relation.id,
        )
        matrices.append(matrix)

    # ── [3] BUCLE DE ESTABILIZACIÓN ───────────────────────────────────────
    #
    # Invariante de terminación: el conjunto admissible de cada variable solo
    # puede reducirse. Con |FOUR| = 4 valores y N variables, el número máximo
    # de mutaciones posibles es 4·N, por lo que el sistema SIEMPRE converge.
    # max_iterations es una salvaguarda adicional ante grafos con ciclos
    # retroalimentados o conectivos futuros más complejos.

    stabilized: bool = False
    iteration: int = 0

    for iteration in range(1, max_iterations + 1):

        # a) Snapshot de los valores effective ANTES del barrido
        before: Dict[str, str] = _snapshot_effective(states)

        # b) Barrido: evaluar todas las matrices
        #    (cada matrix.evaluate() puede mutar los VariableState internamente)
        any_mutation: bool = False
        for matrix in matrices:
            if matrix.evaluate():
                any_mutation = True

        # c) Diff: detectar qué variables mutaron y registrar ExecutionAction
        for var_id, old_eff in before.items():
            new_eff = states[var_id].effective
            if new_eff != old_eff:
                actions.append(
                    ExecutionAction(
                        step=global_step,
                        variable_id=var_id,
                        old_value=_to_evidential(old_eff),
                        new_value=_to_evidential(new_eff),
                        description=_build_description(
                            var_id, old_eff, new_eff, iteration
                        ),
                        is_stabilized=False,  # aún no confirmamos punto fijo
                    )
                )
                global_step += 1

        # d) ¿Punto fijo? → Ninguna matriz produjo mutación en este ciclo
        if not any_mutation:
            stabilized = True
            # Acción de cierre: señal explícita de estabilización para el front-end
            actions.append(
                ExecutionAction(
                    step=global_step,
                    variable_id="__system__",
                    old_value=EvidentialValue.NONE,   # valor semántico neutro
                    new_value=EvidentialValue.NONE,
                    description=(
                        f"[iter={iteration}] Sistema estabilizado: "
                        f"punto fijo alcanzado en {iteration} iteración(es). "
                        f"Ninguna variable mutó en el último ciclo de propagación."
                    ),
                    is_stabilized=True,
                )
            )
            global_step += 1
            break

    # Marcar is_stabilized=True en la última acción real si el bucle agotó
    # las iteraciones sin estabilizarse (el break no se ejecutó).
    # En este caso `stabilized` permanece False y no añadimos acción de cierre.

    # ── [4] FINALIZACIÓN ──────────────────────────────────────────────────
    #
    # 4a. Reescribir los valores effective finales en el modelo Pydantic.
    #     Iteramos sobre la lista original para preservar el orden del front-end.

    for var in snapshot.logic.logic_set.variables:
        final_effective = states[var.id].effective
        var.value = _to_evidential(final_effective)

    # 4b. Construir e inyectar el ExecutionTrace

    snapshot.execution_trace = ExecutionTrace(
        actions=actions,
        stabilized=stabilized,
        total_iterations=iteration,  # última iteración ejecutada (o max si no convergió)
    )

    return snapshot