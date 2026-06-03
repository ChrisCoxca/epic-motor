"""
core/connectives.py
===================
Núcleo matemático puro — Conectivos lógicos de Belnap.

Sin dependencias externas (ni Pydantic, ni FastAPI). Solo Python stdlib
y la clase `VariableState` de `core.belnap`.

Teoría: Implicación Material en FOUR
--------------------------------------
La implicación material (p → q) en la lógica de Belnap de cuatro valores
se define mediante la siguiente tabla de verdad en ≤_t (retículo de verdad):

        p \\ q  |  N    F    V    B
    -----------+--------------------
        N      |  B    B    B    B     (sin info sobre p: cualquier q es posible)
        F      |  V    V    V    V     (p falso → implicación trivialmente verdadera)
        V      |  N    F    V    B     (p verdadero → z hereda el valor de q)
        B      |  B    B    B    B     (p sobre-determinado → z sobre-determinado)

El Motor no evalúa esta tabla directamente; opera con **restricciones de
conjuntos admisibles** sobre el retículo de información (≤_k), lo que
garantiza la monotonía de la propagación.

Reglas de propagación implementadas
-------------------------------------
Dado z = (p → q):

  UI+ (Modus Ponens restringido):
    Condición: z tiene evidencia positiva  AND  p tiene evidencia positiva
    Acción   : q.restrict({"V", "B"})
    Justif.  : Si p es al menos parcialmente verdadero y z también, entonces
               q debe ser al menos parcialmente verdadero.

  UI- (Modus Tollens restringido):
    Condición: z tiene evidencia positiva  AND  q tiene evidencia negativa
    Acción   : p.restrict({"F", "B"})
    Justif.  : Si la implicación se sostiene y q es al menos parcialmente
               falso, entonces p debe ser al menos parcialmente falso
               (contrapositiva: ¬q → ¬p).

Definición de "evidencia positiva" y "evidencia negativa"
-----------------------------------------------------------
  Evidencia positiva de x : x.effective ∈ {"V", "B"}
      → x tiene alguna evidencia de ser verdadero
  Evidencia negativa  de x : x.effective ∈ {"F", "B"}
      → x tiene alguna evidencia de ser falso

  ("B" aparece en ambos porque es sobre-determinado: tiene evidencia
  tanto de ser verdadero como de ser falso.)

Extensibilidad
--------------
La clase `ImplicationMatrix` es la plantilla base.  Para añadir otros
conectivos (AND, OR, NOT, BICONDITIONAL) basta crear nuevas clases que
sigan el mismo contrato: recibir `VariableState` en su constructor e
implementar `evaluate() -> bool`.
"""

from __future__ import annotations

from typing import Set

from core.belnap import VariableState

# ---------------------------------------------------------------------------
# Constantes de evidencia
# ---------------------------------------------------------------------------

#: Valores que representan evidencia positiva (x es al menos parcialmente V)
POSITIVE_EVIDENCE: Set[str] = {"V", "B"}

#: Valores que representan evidencia negativa (x es al menos parcialmente F)
NEGATIVE_EVIDENCE: Set[str] = {"F", "B"}

#: Restricción aplicada a q bajo UI+: q debe ser al menos parcialmente verdadero
_RESTRICT_POSITIVE: Set[str] = {"V", "B"}

#: Restricción aplicada a p bajo UI-: p debe ser al menos parcialmente falso
_RESTRICT_NEGATIVE: Set[str] = {"F", "B"}


# ---------------------------------------------------------------------------
# ImplicationMatrix
# ---------------------------------------------------------------------------

class ImplicationMatrix:
    """
    Evaluador de la implicación material p → q = z en la lógica de Belnap.

    Opera mediante restricciones monotónicas sobre los conjuntos admisibles
    de `VariableState`, sin tabla de verdad explícita. Cada llamada a
    `evaluate()` es idempotente: si no hay nueva información que propagar,
    devuelve False sin modificar ningún estado.

    Attributes
    ----------
    p : VariableState
        Antecedente de la implicación.
    q : VariableState
        Consecuente de la implicación.
    z : VariableState
        Resultado de la implicación (p → q). Puede ser una variable
        auxiliar fijada en "V" si la implicación es una regla axiomática.

    Design Note
    -----------
    El constructor recibe referencias directas a `VariableState`.  Esto es
    intencional: el Motor mantiene un diccionario `{var_id: VariableState}`
    y pasa las mismas instancias a todas las matrices que involucran esa
    variable, de modo que una restricción en `p` dentro de esta matriz se
    refleja automáticamente en cualquier otra matriz donde `p` participe.
    Es el patrón de "nodo compartido" del grafo de propagación.

    Examples
    --------
    >>> p = VariableState("V")   # p es Verdadero
    >>> q = VariableState("N")   # q sin información
    >>> z = VariableState("V")   # la regla p→q se sostiene (z=V)
    >>>
    >>> # Primer ciclo: UI+ debe propagar V a q
    >>> matrix = ImplicationMatrix(p, q, z)
    >>> matrix.evaluate()
    True                          # q.admissible se redujo
    >>> q.effective
    'V'
    >>>
    >>> # Segundo ciclo: sin nueva información
    >>> matrix.evaluate()
    False
    """

    __slots__ = ("p", "q", "z", "_relation_id")

    def __init__(
        self,
        p: VariableState,
        q: VariableState,
        z: VariableState,
        relation_id: str = "<anon>",
    ) -> None:
        """
        Inicializa la matriz con las tres variables de la implicación.

        Parameters
        ----------
        p           : Antecedente de la implicación (VariableState).
        q           : Consecuente de la implicación (VariableState).
        z           : Resultado de p → q (VariableState).
        relation_id : Identificador de la relación para mensajes de depuración.
                      No afecta la lógica matemática.
        """
        self.p = p
        self.q = q
        self.z = z
        self._relation_id = relation_id

    # ------------------------------------------------------------------
    # evaluate
    # ------------------------------------------------------------------

    def evaluate(self) -> bool:
        """
        Aplica las reglas de propagación UI+ y UI- de la implicación.

        Propagación hacia adelante (UI+ — Modus Ponens restringido)
        -----------------------------------------------------------
        Condición : z.effective ∈ {"V", "B"}   (z tiene evidencia positiva)
                    AND
                    p.effective ∈ {"V", "B"}   (p tiene evidencia positiva)
        Acción    : q.restrict({"V", "B"})
        Semántica : Si la implicación se sostiene y p es (al menos
                    parcialmente) verdadero, entonces q también debe ser
                    (al menos parcialmente) verdadero.

        Propagación hacia atrás (UI- — Modus Tollens restringido)
        ----------------------------------------------------------
        Condición : z.effective ∈ {"V", "B"}   (z tiene evidencia positiva)
                    AND
                    q.effective ∈ {"F", "B"}   (q tiene evidencia negativa)
        Acción    : p.restrict({"F", "B"})
        Semántica : Si la implicación se sostiene y q es (al menos
                    parcialmente) falso, entonces p debe ser (al menos
                    parcialmente) falso (contrapositiva monotónica).

        Returns
        -------
        bool
            True  → al menos una variable (p, q, o z) fue mutada.
            False → ningún conjunto admisible cambió en este ciclo.

        Note
        ----
        Ambas reglas se evalúan en el mismo ciclo.  El orden importa
        sutilmente: UI+ puede cambiar q.effective, pero eso no afecta la
        condición de UI- en este ciclo (UI- lee q.effective *antes* de que
        UI+ lo modifique, ya que la condición se captura antes de llamar a
        restrict).  Este comportamiento es correcto y consistente con la
        semántica de punto fijo: en el siguiente ciclo, el Motor re-evaluará
        con los valores actualizados.
        """
        mutated = False

        # ── Capturar estado antes de cualquier restricción ──────────────────
        # (evita que el resultado de UI+ afecte la condición de UI- en el
        # mismo ciclo, manteniendo la semántica de evaluación simultánea)
        z_is_positive = self.z.effective in POSITIVE_EVIDENCE
        p_is_positive = self.p.effective in POSITIVE_EVIDENCE
        q_is_negative = self.q.effective in NEGATIVE_EVIDENCE

        # ── UI+ : Modus Ponens restringido ──────────────────────────────────
        #
        #   z tiene evidencia positiva  ∧  p tiene evidencia positiva
        #   ──────────────────────────────────────────────────────────
        #                   q.restrict({"V", "B"})
        #
        if z_is_positive and p_is_positive:
            if self.q.restrict(_RESTRICT_POSITIVE):
                mutated = True

        # ── UI- : Modus Tollens restringido ─────────────────────────────────
        #
        #   z tiene evidencia positiva  ∧  q tiene evidencia negativa
        #   ──────────────────────────────────────────────────────────
        #                   p.restrict({"F", "B"})
        #
        if z_is_positive and q_is_negative:
            if self.p.restrict(_RESTRICT_NEGATIVE):
                mutated = True

        return mutated

    # ------------------------------------------------------------------
    # Representación para depuración
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"ImplicationMatrix("
            f"rel={self._relation_id!r}, "
            f"p={self.p.effective!r}, "
            f"q={self.q.effective!r}, "
            f"z={self.z.effective!r}"
            f")"
        )
