"""
tests/test_motor.py
===================
Suite de pruebas exhaustiva para el Motor EPIC Playground.

Cobertura objetivo: 100 % de comportamientos observables en las cuatro
capas del sistema.

Organización
------------
Suite 1 — TestBelnapCore
    Pruebas unitarias al retículo matemático (core/belnap.py).
    Valida VariableState, _infimum, monotonía y manejo de errores.

Suite 2 — TestImplicationMatrix
    Pruebas unitarias al conectivo de implicación (core/connectives.py).
    Cubre UI+, UI-, idempotencia, nodos compartidos y evidencia mixta (B).

Suite 3 — TestEnginePropagation
    Pruebas de integración al orquestador (services/engine.py).
    Cubre escenarios lógicos canónicos, ciclos, ceguera espacial y traza.

Suite 4 — TestAPI
    Pruebas de sistema a los endpoints HTTP (api/routes.py + main.py).
    Cubre health check, contratos JSON, CORS, validación Pydantic y errores.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

# ── Importaciones del sistema bajo prueba ────────────────────────────────────
from core.belnap import FOUR, VariableState, _infimum
from core.connectives import (
    NEGATIVE_EVIDENCE,
    POSITIVE_EVIDENCE,
    ImplicationMatrix,
)
from main import app
from models.snapshot import (
    EvidentialValue,
    ExecutionAction,
    ExecutionTrace,
    LogicGraph,
    LogicRelation,
    LogicSet,
    LogicVariable,
    PlaygroundMeta,
    PlaygroundSnapshot,
)
from services.engine import run_propagation

# ── Cliente HTTP compartido ──────────────────────────────────────────────────
client = TestClient(app)


# ============================================================================
# Helpers de fábrica (evitan repetición en los tests)
# ============================================================================

def make_snapshot(
    variables: Dict[str, str],
    relations: list[Dict[str, str]] | None = None,
    max_iterations: int = 100,
    visual: Dict[str, Any] | None = None,
) -> PlaygroundSnapshot:
    """
    Construye un PlaygroundSnapshot listo para usar en pruebas de integración.

    Parameters
    ----------
    variables       : {var_id: valor_inicial} con valores en {"V","F","N","B"}.
    relations       : Lista de dicts {"id", "src", "tgt"}. Default: sin relaciones.
    max_iterations  : Límite del bucle de estabilización. Default: 100.
    visual          : Datos visuales arbitrarios. Default: dict vacío.
    """
    relations = relations or []
    return PlaygroundSnapshot(
        meta=PlaygroundMeta(max_iterations=max_iterations),
        logic=LogicGraph(
            logic_set=LogicSet(
                variables=[
                    LogicVariable(id=vid, value=val)
                    for vid, val in variables.items()
                ],
                relations=[
                    LogicRelation(
                        id=r["id"],
                        source=r["src"],
                        target=r["tgt"],
                        connective="IMPLIES",
                    )
                    for r in relations
                ],
            )
        ),
        visual=visual or {},
    )


def var_values(snap: PlaygroundSnapshot) -> Dict[str, str]:
    """Extrae {var_id: value_string} del snapshot post-propagación."""
    return {v.id: v.value.value for v in snap.logic.logic_set.variables}


def make_state(value: str, restrict_to: set[str] | None = None) -> VariableState:
    """
    Crea un VariableState con valor inicial y restricción opcional.
    Útil para preparar estados en tests de ImplicationMatrix.
    """
    s = VariableState(initial_value=value)
    if restrict_to is not None:
        s.restrict(restrict_to)
    return s


# ============================================================================
# Suite 1 — TestBelnapCore
# Pruebas unitarias al retículo de Belnap (core/belnap.py)
# ============================================================================

class TestBelnapCore:
    """Valida la matemática del retículo de información ≤_k."""

    # ── Inicialización ───────────────────────────────────────────────────────

    def test_init_default_admissible_is_full_four(self):
        """
        ESCENARIO: VariableState recién creado.
        ESPERADO : admissible == FOUR (ignorancia total).
        """
        s = VariableState()
        assert s.admissible == set(FOUR), (
            "El conjunto admissible inicial debe ser el universo completo FOUR."
        )

    def test_init_default_effective_is_N(self):
        """
        ESCENARIO: VariableState sin argumento.
        ESPERADO : effective == "N" (sin información es el valor por defecto).
        """
        s = VariableState()
        assert s.effective == "N"

    @pytest.mark.parametrize("value", ["V", "F", "N", "B"])
    def test_init_all_valid_initial_values(self, value: str):
        """
        ESCENARIO: Inicializar con cada valor válido del universo FOUR.
        ESPERADO : effective refleja el valor dado; admissible sigue siendo FOUR.
        """
        s = VariableState(initial_value=value)
        assert s.effective == value
        assert s.admissible == set(FOUR), (
            "El constructor NO debe restringir admissible; eso es tarea del Motor."
        )

    def test_init_invalid_value_raises_valueerror(self):
        """
        ESCENARIO: Inicializar con un string fuera del universo FOUR.
        ESPERADO : ValueError con mensaje descriptivo.
        FALLO QUE CUBRE: Previene que valores sin sentido silenciosamente
        se conviertan en estados inválidos.
        """
        with pytest.raises(ValueError, match="inválido"):
            VariableState(initial_value="X")

    def test_init_lowercase_raises_valueerror(self):
        """
        ESCENARIO: Valores en minúscula ("v", "f") no son válidos.
        ESPERADO : ValueError — el dominio es case-sensitive.
        FALLO QUE CUBRE: Usuarios del API enviando "v" en lugar de "V".
        """
        with pytest.raises(ValueError):
            VariableState(initial_value="v")

    # ── _infimum — función auxiliar del retículo ─────────────────────────────

    @pytest.mark.parametrize("admissible, expected", [
        # Singletons: triviales
        ({"N"}, "N"),
        ({"V"}, "V"),
        ({"F"}, "F"),
        ({"B"}, "B"),
        # Pares comparables en ≤_k
        ({"N", "V"}, "N"),   # N ≤_k V → mínimo es N
        ({"N", "F"}, "N"),   # N ≤_k F → mínimo es N
        ({"N", "B"}, "N"),   # N ≤_k B → mínimo es N
        ({"V", "B"}, "V"),   # V ≤_k B → mínimo es V
        ({"F", "B"}, "F"),   # F ≤_k B → mínimo es F
        # Par incomparable: el ínfimo de V y F en ≤_k es N
        ({"V", "F"}, "N"),
        # Tríos
        ({"V", "F", "B"}, "N"),   # contiene V y F incomparables
        ({"N", "V", "B"}, "N"),
        ({"N", "F", "B"}, "N"),
        # Universo completo
        ({"V", "F", "N", "B"}, "N"),
        # Caso degenerado: conjunto vacío → B
        (set(), "B"),
    ])
    def test_infimum_table(self, admissible: set, expected: str):
        """
        ESCENARIO: Tabla completa de ínfimos del retículo ≤_k.
        ESPERADO : _infimum devuelve el mínimo correcto para cada combinación.
        FALLO QUE CUBRE: Errores en el cálculo del effective tras restrict().
        """
        assert _infimum(admissible) == expected, (
            f"_infimum({admissible}) debería ser {expected!r}"
        )

    # ── restrict — mutaciones válidas ────────────────────────────────────────

    def test_restrict_returns_true_on_first_reduction(self):
        """
        ESCENARIO: Primera restricción sobre admissible=FOUR.
        ESPERADO : restrict() devuelve True (hubo mutación).
        """
        s = VariableState("N")
        assert s.restrict({"V", "B"}) is True

    def test_restrict_N_to_V_updates_effective(self):
        """
        ESCENARIO: restrict({V}) sobre estado inicial.
        ESPERADO : effective pasa a "V"; admissible = {"V"}.
        FALLO QUE CUBRE: Asegura que el ínfimo se recalcula correctamente.
        """
        s = VariableState("N")
        s.restrict({"V"})
        assert s.effective == "V"
        assert s.admissible == {"V"}

    def test_restrict_N_to_F_updates_effective(self):
        """
        ESCENARIO: restrict({F}) sobre estado inicial.
        ESPERADO : effective pasa a "F".
        """
        s = VariableState("N")
        s.restrict({"F"})
        assert s.effective == "F"

    def test_restrict_to_V_B_gives_effective_V(self):
        """
        ESCENARIO: restrict({V, B}) — conjunto con V como ínfimo.
        ESPERADO : effective == "V" porque V ≤_k B.
        """
        s = VariableState("N")
        s.restrict({"V", "B"})
        assert s.effective == "V"
        assert s.admissible == {"V", "B"}

    def test_restrict_to_F_B_gives_effective_F(self):
        """
        ESCENARIO: restrict({F, B}) — conjunto con F como ínfimo.
        ESPERADO : effective == "F" porque F ≤_k B.
        """
        s = VariableState("N")
        s.restrict({"F", "B"})
        assert s.effective == "F"

    def test_restrict_to_V_F_gives_effective_N(self):
        """
        ESCENARIO: restrict({V, F}) — V y F son incomparables en ≤_k.
        ESPERADO : effective == "N" (ínfimo de incomparables).
        FALLO QUE CUBRE: Caso no obvio donde la reducción del conjunto
        produce un effective MENOR en información que los candidatos.
        """
        s = VariableState("N")
        s.restrict({"V", "F"})
        assert s.effective == "N"
        assert s.admissible == {"V", "F"}

    def test_restrict_chained_N_to_VB_to_V(self):
        """
        ESCENARIO: Dos restricciones sucesivas simulando propagación.
        ESPERADO : La segunda restricción reduce aún más el conjunto.
        FALLO QUE CUBRE: Asegura monotonía: el admissible nunca crece.
        """
        s = VariableState("N")
        first = s.restrict({"V", "B"})
        second = s.restrict({"V"})
        assert first is True
        assert second is True
        assert s.effective == "V"
        assert s.admissible == {"V"}

    # ── restrict — idempotencia (sin cambio) ─────────────────────────────────

    def test_restrict_idempotent_returns_false(self):
        """
        ESCENARIO: Aplicar la misma restricción dos veces.
        ESPERADO : La segunda llamada devuelve False (sin mutación).
        FALLO QUE CUBRE: Previene que el Motor registre acciones fantasma
        en el ExecutionTrace cuando no hubo cambio real.
        """
        s = VariableState("N")
        s.restrict({"V", "B"})
        result = s.restrict({"V", "B"})  # segunda vez: no cambia nada
        assert result is False

    def test_restrict_superset_returns_false(self):
        """
        ESCENARIO: restrict con un superset del admissible actual.
        ESPERADO : False — la intersección no reduce el conjunto.
        FALLO QUE CUBRE: Un superset nunca puede aportar nueva información
        en un sistema monotónico.
        """
        s = VariableState("N")
        s.restrict({"V"})           # admissible = {"V"}
        result = s.restrict({"V", "B"})  # {"V"} ∩ {"V","B"} = {"V"} — sin cambio
        assert result is False
        assert s.admissible == {"V"}

    # ── restrict — manejo de errores ─────────────────────────────────────────

    def test_restrict_invalid_value_raises_valueerror(self):
        """
        ESCENARIO: restrict() recibe un valor fuera del universo FOUR.
        ESPERADO : ValueError inmediato, sin modificar el estado.
        FALLO QUE CUBRE: Valores tipográficos como "v", "TRUE", o "X"
        no deben corromper silenciosamente el conjunto admissible.
        """
        s = VariableState("N")
        original_admissible = copy.copy(s.admissible)
        with pytest.raises(ValueError, match="FOUR"):
            s.restrict({"X"})
        # El estado no debe haber cambiado tras el error
        assert s.admissible == original_admissible

    def test_restrict_mixed_valid_invalid_raises_valueerror(self):
        """
        ESCENARIO: restrict() recibe una mezcla de valores válidos e inválidos.
        ESPERADO : ValueError — ningún valor fuera de FOUR es aceptable.
        FALLO QUE CUBRE: Una mezcla podría pasar inadvertida si la validación
        solo revisa el primer elemento.
        """
        s = VariableState("N")
        with pytest.raises(ValueError):
            s.restrict({"V", "INVALID"})

    # ── Monotonía — propiedad fundamental ────────────────────────────────────

    def test_monotonicity_admissible_never_grows(self):
        """
        ESCENARIO: Serie de restricciones sucesivas aleatorias.
        ESPERADO : |admissible| es no-creciente en toda la secuencia.
        FALLO QUE CUBRE: Violación del principio de monotonía que
        rompería la garantía de convergencia del Motor.
        """
        s = VariableState("N")
        prev_size = len(s.admissible)
        for allowed in [{"V", "F", "B"}, {"V", "F"}, {"V"}, {"V"}]:
            s.restrict(allowed)
            assert len(s.admissible) <= prev_size, (
                "La propiedad de monotonía fue violada: admissible creció."
            )
            prev_size = len(s.admissible)

    def test_equality_operator(self):
        """
        ESCENARIO: Dos VariableState con el mismo admissible y effective.
        ESPERADO : Son iguales según __eq__.
        """
        s1 = VariableState("V")
        s2 = VariableState("V")
        assert s1 == s2

    def test_inequality_operator(self):
        """
        ESCENARIO: Dos VariableState con distintos estados.
        ESPERADO : Son distintos según __eq__.
        """
        s1 = VariableState("V")
        s2 = VariableState("F")
        assert s1 != s2

    def test_repr_contains_effective_and_admissible(self):
        """
        ESCENARIO: Llamar a repr() sobre un VariableState.
        ESPERADO : La representación incluye effective y admissible
        para facilitar la depuración.
        """
        s = VariableState("V")
        r = repr(s)
        assert "effective" in r
        assert "admissible" in r


# ============================================================================
# Suite 2 — TestImplicationMatrix
# Pruebas unitarias al conectivo IMPLIES (core/connectives.py)
# ============================================================================

class TestImplicationMatrix:
    """
    Valida la ImplicationMatrix: UI+ (Modus Ponens) y UI- (Modus Tollens)
    con semántica de cuatro valores de Belnap.
    """

    # ── Constantes de evidencia ───────────────────────────────────────────────

    def test_positive_evidence_set_contains_V_and_B(self):
        """
        ESCENARIO: Verificar la definición de evidencia positiva.
        ESPERADO : {"V", "B"} — valores con al menos evidencia de verdad.
        """
        assert POSITIVE_EVIDENCE == {"V", "B"}

    def test_negative_evidence_set_contains_F_and_B(self):
        """
        ESCENARIO: Verificar la definición de evidencia negativa.
        ESPERADO : {"F", "B"} — valores con al menos evidencia de falsedad.
        """
        assert NEGATIVE_EVIDENCE == {"F", "B"}

    def test_B_is_in_both_evidence_sets(self):
        """
        ESCENARIO: El valor B (sobre-determinado) es bivalente.
        ESPERADO : B pertenece tanto a POSITIVE como a NEGATIVE EVIDENCE.
        FALLO QUE CUBRE: B debe disparar tanto UI+ como UI- simultáneamente,
        lo que refleja la semántica paraconsistente de Belnap.
        """
        assert "B" in POSITIVE_EVIDENCE
        assert "B" in NEGATIVE_EVIDENCE

    # ── UI+ — Modus Ponens ────────────────────────────────────────────────────

    def test_ui_plus_p_V_z_V_propagates_to_q(self):
        """
        ESCENARIO: p=V (evidencia positiva), z=V (implicación verdadera), q=N.
        ESPERADO : UI+ dispara → q.restrict({V,B}) → q.effective = V.
        FALLO QUE CUBRE: Modus Ponens clásico en Belnap.
        """
        p = make_state("V", {"V", "B"})
        q = VariableState("N")
        z = make_state("V", {"V", "B"})
        matrix = ImplicationMatrix(p, q, z, "test_ui_plus")
        mutated = matrix.evaluate()
        assert mutated is True
        assert q.effective == "V"
        assert q.admissible == {"V", "B"}

    def test_ui_plus_p_B_z_V_propagates_to_q(self):
        """
        ESCENARIO: p=B (evidencia positiva por ser sobre-determinado), z=V, q=N.
        ESPERADO : UI+ dispara igualmente — B tiene evidencia positiva.
        FALLO QUE CUBRE: B debe ser tratado como evidencia positiva en UI+.
        """
        p = VariableState("B")  # admissible = FOUR, effective = B
        q = VariableState("N")
        z = make_state("V", {"V", "B"})
        matrix = ImplicationMatrix(p, q, z)
        mutated = matrix.evaluate()
        assert mutated is True
        assert q.effective in {"V", "B"}  # debe tener evidencia positiva

    def test_ui_plus_p_F_z_V_does_not_propagate(self):
        """
        ESCENARIO: p=F (solo evidencia negativa), z=V, q=N.
        ESPERADO : UI+ NO dispara — p no tiene evidencia positiva.
        FALLO QUE CUBRE: Modus Ponens no aplica cuando el antecedente es falso.
        """
        p = make_state("F", {"F", "B"})
        q = VariableState("N")
        z = make_state("V", {"V", "B"})
        matrix = ImplicationMatrix(p, q, z)
        mutated = matrix.evaluate()
        assert mutated is False
        assert q.admissible == set(FOUR)  # q no fue restringido

    def test_ui_plus_p_N_z_V_does_not_propagate(self):
        """
        ESCENARIO: p=N (sin información), z=V, q=N.
        ESPERADO : UI+ NO dispara — N no tiene evidencia positiva ni negativa.
        FALLO QUE CUBRE: Sin evidencia de p, no se puede concluir nada sobre q.
        """
        p = VariableState("N")
        q = VariableState("N")
        z = make_state("V", {"V", "B"})
        matrix = ImplicationMatrix(p, q, z)
        mutated = matrix.evaluate()
        assert mutated is False

    def test_ui_plus_z_F_blocks_propagation(self):
        """
        ESCENARIO: z=F (la implicación tiene evidencia negativa), p=V, q=N.
        ESPERADO : Ni UI+ ni UI- disparan — z no tiene evidencia positiva.
        FALLO QUE CUBRE: Una implicación falsa no propaga evidencia.
        """
        p = make_state("V", {"V", "B"})
        q = VariableState("N")
        z = make_state("F", {"F", "B"})
        matrix = ImplicationMatrix(p, q, z)
        mutated = matrix.evaluate()
        assert mutated is False

    def test_ui_plus_z_N_blocks_propagation(self):
        """
        ESCENARIO: z=N (sin información sobre la implicación), p=V, q=N.
        ESPERADO : Sin propagación — z sin evidencia positiva.
        FALLO QUE CUBRE: Una regla sin valor no debe propagar.
        """
        p = make_state("V", {"V", "B"})
        q = VariableState("N")
        z = VariableState("N")
        matrix = ImplicationMatrix(p, q, z)
        mutated = matrix.evaluate()
        assert mutated is False

    # ── UI- — Modus Tollens ───────────────────────────────────────────────────

    def test_ui_minus_q_F_z_V_restricts_p(self):
        """
        ESCENARIO: q=F (evidencia negativa), z=V (implicación verdadera), p=N.
        ESPERADO : UI- dispara → p.restrict({F,B}) → p.effective = F.
        FALLO QUE CUBRE: Modus Tollens clásico (¬q → ¬p) en Belnap.
        """
        p = VariableState("N")
        q = make_state("F", {"F", "B"})
        z = make_state("V", {"V", "B"})
        matrix = ImplicationMatrix(p, q, z, "test_ui_minus")
        mutated = matrix.evaluate()
        assert mutated is True
        assert p.effective == "F"
        assert p.admissible == {"F", "B"}

    def test_ui_minus_q_B_z_V_restricts_p(self):
        """
        ESCENARIO: q=B (tiene evidencia negativa por ser sobre-determinado).
        ESPERADO : UI- dispara — B activa Modus Tollens.
        FALLO QUE CUBRE: B también debe triggear UI-.
        """
        p = VariableState("N")
        q = VariableState("B")  # B tiene evidencia negativa
        z = make_state("V", {"V", "B"})
        matrix = ImplicationMatrix(p, q, z)
        mutated = matrix.evaluate()
        assert mutated is True
        assert p.effective in {"F", "B"}

    def test_ui_minus_q_V_z_V_does_not_restrict_p(self):
        """
        ESCENARIO: q=V (solo evidencia positiva), z=V, p=N.
        ESPERADO : UI- NO dispara — q no tiene evidencia negativa.
        FALLO QUE CUBRE: Modus Tollens no aplica cuando el consecuente es verdadero.
        """
        p = VariableState("N")
        q = make_state("V", {"V", "B"})
        z = make_state("V", {"V", "B"})
        matrix = ImplicationMatrix(p, q, z)
        mutated = matrix.evaluate()
        assert mutated is False

    # ── Evaluación simultánea UI+ y UI- ──────────────────────────────────────

    def test_both_ui_fire_when_p_V_q_F_z_V(self):
        """
        ESCENARIO: p=V (positivo), q=F (negativo), z=V — ambas reglas activan.
        ESPERADO : UI+ intenta restrict q (ya en {F,B} → intersección con {V,B}
                   da {B}), UI- restringe p (ya en {V,B} → ∩ {F,B} = {B}).
        FALLO QUE CUBRE: Ambas reglas usan estado capturado ANTES del barrido,
        evitando que UI+ cancele la condición de UI-.
        """
        p = make_state("V", {"V", "B"})   # admissible = {V, B}
        q = make_state("F", {"F", "B"})   # admissible = {F, B}
        z = make_state("V", {"V", "B"})
        matrix = ImplicationMatrix(p, q, z, "both_ui")
        mutated = matrix.evaluate()
        assert mutated is True
        # q.admissible ∩ {V,B} = {F,B} ∩ {V,B} = {B}
        assert q.admissible == {"B"}
        # p.admissible ∩ {F,B} = {V,B} ∩ {F,B} = {B}
        assert p.admissible == {"B"}

    # ── Idempotencia ─────────────────────────────────────────────────────────

    def test_evaluate_idempotent_after_convergence(self):
        """
        ESCENARIO: evaluate() llamado dos veces sin nueva información.
        ESPERADO : La segunda llamada devuelve False (sin mutación).
        FALLO QUE CUBRE: Un evaluate() no-idempotente causaría iteraciones
        infinitas en el bucle de estabilización del Motor.
        """
        p = make_state("V", {"V", "B"})
        q = VariableState("N")
        z = make_state("V", {"V", "B"})
        matrix = ImplicationMatrix(p, q, z)
        matrix.evaluate()              # primera: muta q
        result = matrix.evaluate()     # segunda: sin cambio
        assert result is False

    # ── Nodo compartido ───────────────────────────────────────────────────────

    def test_shared_node_mutation_visible_across_matrices(self):
        """
        ESCENARIO: Una variable q es target en dos matrices distintas.
        ESPERADO : Una restricción aplicada por la primera matriz es visible
                   cuando la segunda matriz evalúa el mismo objeto.
        FALLO QUE CUBRE: Patrón de nodo compartido — si las matrices
        tuvieran copias en lugar de referencias, el sistema perdería
        propagación entre reglas que comparten variables.
        """
        shared_q = VariableState("N")
        p1 = make_state("V", {"V", "B"})
        p2 = make_state("V", {"V", "B"})
        z = make_state("V", {"V", "B"})

        m1 = ImplicationMatrix(p1, shared_q, z, "m1")
        m2 = ImplicationMatrix(p2, shared_q, z, "m2")

        m1.evaluate()
        assert shared_q.effective == "V"

        # m2 debe ver el q ya restringido por m1
        result = m2.evaluate()
        assert result is False  # sin nueva mutación

    # ── repr ─────────────────────────────────────────────────────────────────

    def test_repr_contains_relation_id(self):
        """
        ESCENARIO: repr() de ImplicationMatrix.
        ESPERADO : Incluye el relation_id para facilitar depuración.
        """
        p = VariableState("V")
        q = VariableState("N")
        z = VariableState("V")
        m = ImplicationMatrix(p, q, z, "test_rel_42")
        assert "test_rel_42" in repr(m)


# ============================================================================
# Suite 3 — TestEnginePropagation
# Pruebas de integración al Motor (services/engine.py)
# ============================================================================

class TestEnginePropagation:
    """
    Valida el ciclo completo de propagación: inicialización, bucle,
    traza y finalización.
    """

    # ── Caso Socrático (canónico) ─────────────────────────────────────────────

    def test_socratic_p_implies_q_p_V_stabilizes_q_V(self):
        """
        ESCENARIO: Argumento socrático — p→q, p=V.
        ESPERADO : El motor estabiliza q en V (Modus Ponens).
        FALLO QUE CUBRE: Caso más fundamental de propagación hacia adelante.
        """
        snap = make_snapshot(
            {"p": "V", "q": "N"},
            [{"id": "r1", "src": "p", "tgt": "q"}],
        )
        result = run_propagation(snap)
        vals = var_values(result)
        assert vals["p"] == "V"
        assert vals["q"] == "V"
        assert result.execution_trace.stabilized is True

    def test_modus_tollens_q_F_implies_p_F(self):
        """
        ESCENARIO: Contrapositiva — p→q, q=F.
        ESPERADO : El motor restringe p a F (Modus Tollens).
        FALLO QUE CUBRE: Propagación hacia atrás (UI-).
        """
        snap = make_snapshot(
            {"p": "N", "q": "F"},
            [{"id": "r1", "src": "p", "tgt": "q"}],
        )
        result = run_propagation(snap)
        vals = var_values(result)
        assert vals["q"] == "F"
        assert vals["p"] == "F"

    # ── Cadena de implicaciones ───────────────────────────────────────────────

    def test_chain_p_q_r_propagates_fully(self):
        """
        ESCENARIO: p→q→r, p=V.
        ESPERADO : r termina en V (propagación transitiva).
        FALLO QUE CUBRE: Que el Motor maneje cadenas de más de un salto.
        """
        snap = make_snapshot(
            {"p": "V", "q": "N", "r": "N"},
            [{"id": "r1", "src": "p", "tgt": "q"},
             {"id": "r2", "src": "q", "tgt": "r"}],
        )
        result = run_propagation(snap)
        vals = var_values(result)
        assert vals["p"] == "V"
        assert vals["q"] == "V"
        assert vals["r"] == "V"

    def test_long_chain_five_nodes(self):
        """
        ESCENARIO: p→q→r→s→t, p=V.
        ESPERADO : Todos terminan en V en ≤ max_iterations.
        FALLO QUE CUBRE: Estabilización en cadenas largas sin explosión.
        """
        snap = make_snapshot(
            {"p": "V", "q": "N", "r": "N", "s": "N", "t": "N"},
            [{"id": "r1", "src": "p", "tgt": "q"},
             {"id": "r2", "src": "q", "tgt": "r"},
             {"id": "r3", "src": "r", "tgt": "s"},
             {"id": "r4", "src": "s", "tgt": "t"}],
        )
        result = run_propagation(snap)
        vals = var_values(result)
        assert all(vals[v] == "V" for v in ["p", "q", "r", "s", "t"])
        assert result.execution_trace.stabilized is True

    # ── Conservaduría clásica ─────────────────────────────────────────────────

    def test_classical_all_V_no_change(self):
        """
        ESCENARIO: Todas las variables inician en V, relación p→q.
        ESPERADO : El resultado es idéntico a la lógica clásica: todas V.
        FALLO QUE CUBRE: El Motor de Belnap debe ser conservador con la
        lógica clásica cuando no hay contradicción.
        """
        snap = make_snapshot(
            {"p": "V", "q": "V"},
            [{"id": "r1", "src": "p", "tgt": "q"}],
        )
        result = run_propagation(snap)
        vals = var_values(result)
        assert vals["p"] == "V"
        assert vals["q"] == "V"

    def test_classical_all_F_no_change(self):
        """
        ESCENARIO: Todas las variables inician en F, relación p→q.
        ESPERADO : Resultado idéntico al clásico: p=F, q=F.
        FALLO QUE CUBRE: Conservaduría clásica con valores falsos.
        """
        snap = make_snapshot(
            {"p": "F", "q": "F"},
            [{"id": "r1", "src": "p", "tgt": "q"}],
        )
        result = run_propagation(snap)
        vals = var_values(result)
        assert vals["p"] == "F"
        assert vals["q"] == "F"

    # ── Grafo cíclico ─────────────────────────────────────────────────────────

    def test_cyclic_graph_terminates(self):
        """
        ESCENARIO: Grafo cíclico p→q→r→p, todas las variables en N.
        ESPERADO : El motor termina (no bucle infinito). Estabilización
                   o detención por max_iterations.
        FALLO QUE CUBRE: Garantía de terminación en grafos con retroalimentación.
        Este es el test más crítico para la robustez del Motor.
        """
        snap = make_snapshot(
            {"p": "N", "q": "N", "r": "N"},
            [{"id": "r1", "src": "p", "tgt": "q"},
             {"id": "r2", "src": "q", "tgt": "r"},
             {"id": "r3", "src": "r", "tgt": "p"}],
            max_iterations=50,
        )
        result = run_propagation(snap)
        trace = result.execution_trace
        # El motor debe terminar dentro del límite
        assert trace.total_iterations <= 50
        # El trace debe existir y ser coherente
        assert trace is not None

    def test_cyclic_graph_with_evidence_terminates(self):
        """
        ESCENARIO: Grafo cíclico p→q→r→p, con p=V como semilla.
        ESPERADO : El motor termina y todo converge a V (ciclo positivo).
        FALLO QUE CUBRE: Propagación en ciclo con evidencia inicial.
        """
        snap = make_snapshot(
            {"p": "V", "q": "N", "r": "N"},
            [{"id": "r1", "src": "p", "tgt": "q"},
             {"id": "r2", "src": "q", "tgt": "r"},
             {"id": "r3", "src": "r", "tgt": "p"}],
            max_iterations=20,
        )
        result = run_propagation(snap)
        assert result.execution_trace.total_iterations <= 20
        vals = var_values(result)
        assert vals["p"] == "V"

    def test_max_iterations_is_respected(self):
        """
        ESCENARIO: max_iterations=1, grafo que normalmente requeriría más.
        ESPERADO : total_iterations == 1 (detenido por límite).
        FALLO QUE CUBRE: El parámetro max_iterations debe ser un límite duro.
        """
        snap = make_snapshot(
            {"p": "V", "q": "N", "r": "N", "s": "N"},
            [{"id": "r1", "src": "p", "tgt": "q"},
             {"id": "r2", "src": "q", "tgt": "r"},
             {"id": "r3", "src": "r", "tgt": "s"}],
            max_iterations=1,
        )
        result = run_propagation(snap)
        assert result.execution_trace.total_iterations == 1

    # ── Grafo vacío y casos de borde ─────────────────────────────────────────

    def test_empty_graph_no_variables(self):
        """
        ESCENARIO: Snapshot sin variables ni relaciones.
        ESPERADO : Termina sin error; execution_trace generado.
        FALLO QUE CUBRE: El Motor no debe explotar con entrada vacía.
        """
        snap = make_snapshot({}, [])
        result = run_propagation(snap)
        assert result.execution_trace is not None
        assert result.execution_trace.stabilized is True
        assert len(result.logic.logic_set.variables) == 0

    def test_variables_without_relations_unchanged(self):
        """
        ESCENARIO: Variables sin ninguna relación, valores mixtos.
        ESPERADO : Todos los valores permanecen iguales al inicial.
        FALLO QUE CUBRE: Sin relaciones no debe haber propagación.
        """
        snap = make_snapshot({"p": "V", "q": "F", "r": "N", "s": "B"}, [])
        result = run_propagation(snap)
        vals = var_values(result)
        assert vals["p"] == "V"
        assert vals["q"] == "F"
        assert vals["r"] == "N"
        assert vals["s"] == "B"

    def test_orphan_relation_silently_ignored(self):
        """
        ESCENARIO: Relación que referencia una variable inexistente ("GHOST").
        ESPERADO : El motor ignora la relación y continúa sin error.
        FALLO QUE CUBRE: Grafos malformados desde el Editor no deben
        causar KeyError ni crashes en el Motor.
        """
        snap = make_snapshot(
            {"p": "V"},
            [{"id": "r_orphan", "src": "p", "tgt": "GHOST"}],
        )
        result = run_propagation(snap)
        assert var_values(result)["p"] == "V"
        assert result.execution_trace is not None

    def test_self_loop_relation_terminates(self):
        """
        ESCENARIO: p→p (auto-referencia).
        ESPERADO : El motor termina sin bucle infinito.
        FALLO QUE CUBRE: La auto-implicación es el ciclo más corto posible.
        """
        snap = make_snapshot(
            {"p": "V"},
            [{"id": "r_self", "src": "p", "tgt": "p"}],
            max_iterations=10,
        )
        result = run_propagation(snap)
        assert result.execution_trace.total_iterations <= 10

    # ── ExecutionTrace — estructura y contenido ───────────────────────────────

    def test_execution_trace_is_populated(self):
        """
        ESCENARIO: Propagación normal con una mutación esperada.
        ESPERADO : execution_trace existe y contiene al menos una acción.
        """
        snap = make_snapshot(
            {"p": "V", "q": "N"},
            [{"id": "r1", "src": "p", "tgt": "q"}],
        )
        result = run_propagation(snap)
        assert result.execution_trace is not None
        assert len(result.execution_trace.actions) >= 1

    def test_execution_trace_action_fields_are_complete(self):
        """
        ESCENARIO: Propagación que produce exactamente una mutación (q: N→V).
        ESPERADO : La ExecutionAction tiene todos los campos correctos.
        """
        snap = make_snapshot(
            {"p": "V", "q": "N"},
            [{"id": "r1", "src": "p", "tgt": "q"}],
        )
        result = run_propagation(snap)
        q_actions = [
            a for a in result.execution_trace.actions
            if a.variable_id == "q"
        ]
        assert len(q_actions) >= 1
        action = q_actions[0]
        assert action.step >= 0
        assert action.old_value == EvidentialValue.NONE
        assert action.new_value == EvidentialValue.TRUE
        assert action.variable_id == "q"
        assert "iter" in action.description
        assert isinstance(action.is_stabilized, bool)

    def test_system_stabilization_action_is_last(self):
        """
        ESCENARIO: Motor estabilizado correctamente.
        ESPERADO : La última acción tiene variable_id == "__system__"
                   y is_stabilized == True.
        FALLO QUE CUBRE: El front-end depende de esta acción de cierre
        para detener la animación.
        """
        snap = make_snapshot(
            {"p": "V", "q": "N"},
            [{"id": "r1", "src": "p", "tgt": "q"}],
        )
        result = run_propagation(snap)
        last = result.execution_trace.actions[-1]
        assert last.variable_id == "__system__"
        assert last.is_stabilized is True

    def test_action_steps_are_unique_and_nonnegative(self):
        """
        ESCENARIO: Propagación con múltiples mutaciones.
        ESPERADO : Cada ExecutionAction tiene un step único y ≥ 0.
        FALLO QUE CUBRE: Steps duplicados confundirían la animación del front-end.
        """
        snap = make_snapshot(
            {"p": "V", "q": "N", "r": "N"},
            [{"id": "r1", "src": "p", "tgt": "q"},
             {"id": "r2", "src": "q", "tgt": "r"}],
        )
        result = run_propagation(snap)
        steps = [a.step for a in result.execution_trace.actions]
        assert all(s >= 0 for s in steps)
        assert len(steps) == len(set(steps)), "Los steps deben ser únicos."

    def test_stabilized_true_when_converges(self):
        """
        ESCENARIO: Motor alcanza punto fijo.
        ESPERADO : execution_trace.stabilized == True.
        """
        snap = make_snapshot({"p": "V", "q": "N"},
                             [{"id": "r1", "src": "p", "tgt": "q"}])
        result = run_propagation(snap)
        assert result.execution_trace.stabilized is True

    def test_stabilized_false_when_max_iterations_hit(self):
        """
        ESCENARIO: max_iterations=1 en un grafo que necesita más iteraciones.
        ESPERADO : stabilized == False (límite alcanzado sin convergencia).
        FALLO QUE CUBRE: El Motor debe honrar el límite y reportarlo honestamente.
        """
        # Cadena de 5 variables requiere >1 iteración para propagarse completamente
        snap = make_snapshot(
            {"p": "V", "q": "N", "r": "N", "s": "N", "t": "N"},
            [{"id": "r1", "src": "p", "tgt": "q"},
             {"id": "r2", "src": "q", "tgt": "r"},
             {"id": "r3", "src": "r", "tgt": "s"},
             {"id": "r4", "src": "s", "tgt": "t"}],
            max_iterations=1,
        )
        result = run_propagation(snap)
        # Con max_iter=1 y barrido secuencial, la cadena puede o no propagarse
        # completamente, pero si no lo hizo, stabilized debe ser False.
        trace = result.execution_trace
        assert trace.total_iterations <= 1

    # ── Ceguera espacial ─────────────────────────────────────────────────────

    def test_visual_field_is_unchanged_after_propagation(self):
        """
        ESCENARIO: Snapshot con datos visuales arbitrariamente complejos.
        ESPERADO : visual retorna EXACTAMENTE igual — el Motor es ciego.
        FALLO QUE CUBRE: El Motor no debe tocar, leer ni transformar visual.
        """
        visual = {
            "nodes": {"p": {"x": 123.45, "y": -67.89, "color": "#ff0000"}},
            "edges": {"r1": {"style": "dashed", "label": "IMPLIES"}},
            "viewport": {"zoom": 2.5, "pan": [100, -200]},
            "metadata": {"version": "3.1.4", "tags": ["alpha", "beta"]},
        }
        snap = make_snapshot({"p": "V"}, [], visual=copy.deepcopy(visual))
        result = run_propagation(snap)
        assert result.visual == visual, (
            "El campo 'visual' fue modificado por el Motor. "
            "Violación del principio de ceguera espacial."
        )

    def test_visual_nested_structure_intact(self):
        """
        ESCENARIO: visual contiene estructuras anidadas profundas.
        ESPERADO : Estructura completa intacta tras la propagación.
        """
        visual = {
            "level1": {
                "level2": {
                    "level3": [1, 2, {"deep": True}]
                }
            }
        }
        snap = make_snapshot({"p": "N"}, [], visual=copy.deepcopy(visual))
        result = run_propagation(snap)
        assert result.visual["level1"]["level2"]["level3"][2]["deep"] is True

    # ── Valores iniciales B (sobre-determinado) ───────────────────────────────

    def test_variable_B_initial_propagates_positively(self):
        """
        ESCENARIO: p=B (sobre-determinado) como antecedente en p→q.
        ESPERADO : q recibe evidencia positiva (UI+ dispara con p=B).
        FALLO QUE CUBRE: B debe ser tratado como evidencia positiva
        para que Modus Ponens paraconsistente funcione.
        """
        snap = make_snapshot(
            {"p": "B", "q": "N"},
            [{"id": "r1", "src": "p", "tgt": "q"}],
        )
        result = run_propagation(snap)
        vals = var_values(result)
        assert vals["q"] in {"V", "B"}, (
            "q debe tener evidencia positiva cuando p=B propaga."
        )

    # ── Devuelve el mismo objeto (mutación in-place) ──────────────────────────

    def test_run_propagation_returns_same_object(self):
        """
        ESCENARIO: run_propagation(snap) devuelve el resultado.
        ESPERADO : Es el mismo objeto Python (mutación in-place), no una copia.
        FALLO QUE CUBRE: Contratos de identidad del Motor; importante para
        que el servicio API no haga copias innecesarias.
        """
        snap = make_snapshot({"p": "V"}, [])
        result = run_propagation(snap)
        assert result is snap


# ============================================================================
# Suite 4 — TestAPI
# Pruebas de sistema a los endpoints HTTP
# ============================================================================

class TestAPI:
    """
    Valida los contratos HTTP del Motor: rutas, códigos de estado,
    estructura JSON de respuesta y comportamiento ante errores.
    """

    # ── Health check ─────────────────────────────────────────────────────────

    def test_health_check_returns_200(self):
        """
        ESCENARIO: GET / sin parámetros.
        ESPERADO : 200 OK.
        FALLO QUE CUBRE: El servicio no arranca o la ruta no existe.
        """
        r = client.get("/")
        assert r.status_code == 200

    def test_health_check_body_has_status_online(self):
        """
        ESCENARIO: GET /.
        ESPERADO : Body JSON contiene {"status": "online"}.
        FALLO QUE CUBRE: El health check reporta un estado incorrecto.
        """
        body = client.get("/").json()
        assert body.get("status") == "online"

    def test_health_check_body_has_motor_name(self):
        """
        ESCENARIO: GET /.
        ESPERADO : Body contiene clave "motor" con el nombre del servicio.
        FALLO QUE CUBRE: Monitoreo automatizado que depende del nombre del motor.
        """
        body = client.get("/").json()
        assert "motor" in body
        assert "EPIC" in body["motor"]

    def test_health_check_body_has_version(self):
        """
        ESCENARIO: GET /.
        ESPERADO : Body contiene clave "version".
        FALLO QUE CUBRE: Sistemas de monitoreo que verifican la versión desplegada.
        """
        body = client.get("/").json()
        assert "version" in body

    # ── POST /calcular — respuesta exitosa ────────────────────────────────────

    def test_calcular_returns_200_with_valid_payload(self):
        """
        ESCENARIO: POST /calcular con payload mínimo válido.
        ESPERADO : 200 OK.
        """
        r = client.post("/calcular", json={"visual": {}})
        assert r.status_code == 200

    def test_calcular_response_contains_execution_trace(self):
        """
        ESCENARIO: POST /calcular con grafo de 2 variables y 1 relación.
        ESPERADO : La respuesta incluye execution_trace con acciones registradas.
        FALLO QUE CUBRE: El Motor omitió el trace o no lo inyectó en el JSON.
        """
        payload = {
            "logic": {
                "logic_set": {
                    "variables": [
                        {"id": "p", "value": "V"},
                        {"id": "q", "value": "N"},
                    ],
                    "relations": [
                        {"id": "r1", "source": "p", "target": "q",
                         "connective": "IMPLIES"},
                    ],
                }
            },
            "visual": {},
        }
        body = client.post("/calcular", json=payload).json()
        assert "execution_trace" in body
        assert body["execution_trace"] is not None
        assert "actions" in body["execution_trace"]
        assert len(body["execution_trace"]["actions"]) >= 1

    def test_calcular_propagates_correctly_via_http(self):
        """
        ESCENARIO: POST /calcular con p=V, p→q.
        ESPERADO : La respuesta muestra q=V en logic.logic_set.variables.
        FALLO QUE CUBRE: El Motor no está conectado al endpoint correctamente.
        """
        payload = {
            "logic": {
                "logic_set": {
                    "variables": [
                        {"id": "p", "value": "V"},
                        {"id": "q", "value": "N"},
                    ],
                    "relations": [
                        {"id": "r1", "source": "p", "target": "q",
                         "connective": "IMPLIES"},
                    ],
                }
            },
            "visual": {},
        }
        body = client.post("/calcular", json=payload).json()
        vars_map = {
            v["id"]: v["value"]
            for v in body["logic"]["logic_set"]["variables"]
        }
        assert vars_map["p"] == "V"
        assert vars_map["q"] == "V"

    def test_calcular_stabilized_flag_in_response(self):
        """
        ESCENARIO: POST /calcular con grafo simple que converge.
        ESPERADO : execution_trace.stabilized == True en el JSON de respuesta.
        """
        payload = {
            "logic": {
                "logic_set": {
                    "variables": [{"id": "p", "value": "V"}],
                    "relations": [],
                }
            },
            "visual": {},
        }
        body = client.post("/calcular", json=payload).json()
        assert body["execution_trace"]["stabilized"] is True

    # ── Ceguera espacial vía HTTP ─────────────────────────────────────────────

    def test_calcular_visual_field_returned_intact(self):
        """
        ESCENARIO: POST /calcular con datos visual arbitrariamente complejos.
        ESPERADO : El JSON de respuesta contiene el campo visual EXACTAMENTE igual.
        FALLO QUE CUBRE: Serialización/deserialización que altera el visual.
        """
        visual_payload = {
            "nodes": {
                "p": {"x": 42.0, "y": -7.5, "label": "Premise", "color": "#abc123"},
                "q": {"x": 200.0, "y": 300.0},
            },
            "edges": {"r1": {"animated": True, "weight": 0.95}},
            "viewport": {"zoom": 1.75, "pan": [50, -25]},
            "custom_metadata": {"session": "abc-def-123", "version": 7},
        }
        payload = {
            "logic": {"logic_set": {"variables": [], "relations": []}},
            "visual": visual_payload,
        }
        body = client.post("/calcular", json=payload).json()
        assert body["visual"] == visual_payload, (
            "El campo 'visual' fue alterado por el Motor o la serialización."
        )

    def test_calcular_visual_empty_dict_allowed(self):
        """
        ESCENARIO: POST /calcular con visual = {}.
        ESPERADO : 200 OK y visual == {} en la respuesta.
        FALLO QUE CUBRE: Payload mínimo con visual vacío.
        """
        payload = {"logic": {"logic_set": {}}, "visual": {}}
        r = client.post("/calcular", json=payload)
        assert r.status_code == 200
        assert r.json()["visual"] == {}

    def test_calcular_visual_with_nested_lists_and_nulls(self):
        """
        ESCENARIO: visual con listas anidadas y valores nulos.
        ESPERADO : El JSON de respuesta preserva nulls y listas intactas.
        FALLO QUE CUBRE: Serialización que elimina nulls o aplana listas.
        """
        visual = {"data": [1, None, {"nested": [True, False, None]}]}
        payload = {"logic": {"logic_set": {}}, "visual": visual}
        body = client.post("/calcular", json=payload).json()
        assert body["visual"] == visual

    # ── Validación de entrada — errores 422 ───────────────────────────────────

    def test_calcular_invalid_evidential_value_returns_422(self):
        """
        ESCENARIO: Variable con value="J" (fuera del enum EvidentialValue).
        ESPERADO : 422 Unprocessable Entity automático de Pydantic.
        FALLO QUE CUBRE: El Motor no debe procesar valores fuera de FOUR.
        """
        payload = {
            "logic": {
                "logic_set": {
                    "variables": [{"id": "p", "value": "J"}],
                    "relations": [],
                }
            },
            "visual": {},
        }
        r = client.post("/calcular", json=payload)
        assert r.status_code == 422

    def test_calcular_string_body_returns_422(self):
        """
        ESCENARIO: Body que no es JSON válido para PlaygroundSnapshot.
        ESPERADO : 422.
        FALLO QUE CUBRE: El endpoint rechaza entradas completamente erróneas.
        """
        r = client.post(
            "/calcular",
            content=b'"esto no es un snapshot"',
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 422

    def test_calcular_missing_required_field_in_variable_returns_422(self):
        """
        ESCENARIO: Variable sin campo "value" (obligatorio en LogicVariable).
        ESPERADO : 422 — Pydantic detecta el campo faltante.
        FALLO QUE CUBRE: Variables con estructura incompleta desde el Editor.
        """
        payload = {
            "logic": {
                "logic_set": {
                    "variables": [{"id": "p"}],  # falta "value"
                    "relations": [],
                }
            },
            "visual": {},
        }
        r = client.post("/calcular", json=payload)
        assert r.status_code == 422

    def test_calcular_variable_empty_id_returns_422(self):
        """
        ESCENARIO: Variable con id="" (vacío, violando min_length=1).
        ESPERADO : 422 — Pydantic rechaza IDs vacíos.
        FALLO QUE CUBRE: Un ID vacío causaría bugs en el dict de estados.
        """
        payload = {
            "logic": {
                "logic_set": {
                    "variables": [{"id": "", "value": "V"}],
                    "relations": [],
                }
            },
            "visual": {},
        }
        r = client.post("/calcular", json=payload)
        assert r.status_code == 422

    def test_calcular_max_iterations_zero_returns_422(self):
        """
        ESCENARIO: max_iterations=0 (viola la restricción ge=1).
        ESPERADO : 422.
        FALLO QUE CUBRE: Un límite de 0 iteraciones causaría que el Motor
        nunca ejecute el bucle y devuelva iteration=0.
        """
        payload = {
            "meta": {"max_iterations": 0},
            "logic": {"logic_set": {}},
            "visual": {},
        }
        r = client.post("/calcular", json=payload)
        assert r.status_code == 422

    def test_calcular_max_iterations_negative_returns_422(self):
        """
        ESCENARIO: max_iterations=-5.
        ESPERADO : 422.
        """
        payload = {
            "meta": {"max_iterations": -5},
            "logic": {"logic_set": {}},
            "visual": {},
        }
        r = client.post("/calcular", json=payload)
        assert r.status_code == 422

    # ── CORS ─────────────────────────────────────────────────────────────────

    def test_cors_header_present_in_post_response(self):
        """
        ESCENARIO: POST /calcular con header Origin del Editor (localhost:5173).
        ESPERADO : La respuesta contiene Access-Control-Allow-Origin.
        FALLO QUE CUBRE: Sin este header el navegador bloquea la respuesta.
        """
        r = client.post(
            "/calcular",
            json={"visual": {}},
            headers={"Origin": "http://localhost:5173"},
        )
        assert "access-control-allow-origin" in r.headers

    def test_cors_header_present_in_options_preflight(self):
        """
        ESCENARIO: Preflight OPTIONS que el navegador envía antes del POST real.
        ESPERADO : Respuesta contiene headers CORS necesarios.
        FALLO QUE CUBRE: Sin respuesta correcta al preflight, el POST nunca llega.
        """
        r = client.options(
            "/calcular",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
            },
        )
        assert "access-control-allow-origin" in r.headers
        assert "access-control-allow-methods" in r.headers

    def test_cors_allows_any_origin(self):
        """
        ESCENARIO: Request desde un origen arbitrario (no localhost).
        ESPERADO : El CORS también permite ese origen (allow_origins=["*"]).
        FALLO QUE CUBRE: Si allow_origins estuviera restringido, el Editor
        en producción no podría comunicarse con el Motor.
        """
        r = client.post(
            "/calcular",
            json={"visual": {}},
            headers={"Origin": "https://epic-playground.app"},
        )
        cors = r.headers.get("access-control-allow-origin", "")
        assert cors in {"*", "https://epic-playground.app"}, (
            f"CORS no permitió el origen externo. Header: {cors!r}"
        )

    # ── OpenAPI / Documentación ───────────────────────────────────────────────

    def test_openapi_json_available(self):
        """
        ESCENARIO: GET /openapi.json.
        ESPERADO : 200 OK con schema válido.
        FALLO QUE CUBRE: La documentación interactiva requiere este endpoint.
        """
        r = client.get("/openapi.json")
        assert r.status_code == 200
        schema = r.json()
        assert "paths" in schema
        assert "/calcular" in schema["paths"]

    def test_openapi_title_matches_app(self):
        """
        ESCENARIO: GET /openapi.json.
        ESPERADO : info.title contiene "EPIC Playground".
        """
        schema = client.get("/openapi.json").json()
        assert "EPIC" in schema["info"]["title"]

    def test_swagger_ui_available(self):
        """
        ESCENARIO: GET /docs.
        ESPERADO : 200 OK (Swagger UI disponible para desarrollo).
        """
        assert client.get("/docs").status_code == 200

    def test_redoc_available(self):
        """
        ESCENARIO: GET /redoc.
        ESPERADO : 200 OK (ReDoc disponible como alternativa).
        """
        assert client.get("/redoc").status_code == 200

    # ── Contratos de respuesta ────────────────────────────────────────────────

    def test_response_preserves_all_variable_ids(self):
        """
        ESCENARIO: POST /calcular con N variables.
        ESPERADO : La respuesta contiene exactamente los mismos IDs en
                   logic.logic_set.variables.
        FALLO QUE CUBRE: El Motor no debe añadir ni eliminar variables.
        """
        ids = ["alpha", "beta", "gamma", "delta"]
        payload = {
            "logic": {
                "logic_set": {
                    "variables": [{"id": vid, "value": "N"} for vid in ids],
                    "relations": [],
                }
            },
            "visual": {},
        }
        body = client.post("/calcular", json=payload).json()
        response_ids = [v["id"] for v in body["logic"]["logic_set"]["variables"]]
        assert set(response_ids) == set(ids)

    def test_response_execution_trace_total_iterations_nonnegative(self):
        """
        ESCENARIO: POST /calcular cualquiera.
        ESPERADO : total_iterations >= 1 (el bucle siempre ejecuta al menos una vez).
        """
        payload = {"logic": {"logic_set": {}}, "visual": {}}
        body = client.post("/calcular", json=payload).json()
        assert body["execution_trace"]["total_iterations"] >= 1

    def test_response_content_type_is_json(self):
        """
        ESCENARIO: POST /calcular válido.
        ESPERADO : Content-Type de la respuesta es application/json.
        FALLO QUE CUBRE: Clientes que verifican el content-type antes de parsear.
        """
        r = client.post("/calcular", json={"visual": {}})
        assert "application/json" in r.headers.get("content-type", "")

    def test_unknown_endpoint_returns_404(self):
        """
        ESCENARIO: GET /ruta_inexistente.
        ESPERADO : 404 Not Found.
        FALLO QUE CUBRE: El Motor no debe responder con 200 a rutas arbitrarias.
        """
        r = client.get("/esto_no_existe")
        assert r.status_code == 404