"""
core/belnap.py
==============
Núcleo matemático puro — Retículo de Belnap (FOUR).

Sin dependencias externas (ni Pydantic, ni FastAPI). Solo Python stdlib.

Teoría
------
La lógica de cuatro valores de Belnap organiza el espacio epistémico en
dos retículos ortogonales:

  Retículo de VERDAD (≤_t):        Retículo de INFORMACIÓN (≤_k):
       V                                    B
      / \\                                 / \\
     ?   ?       (no hay orden          V   F
      \\ /         entre V y F)           \\ /
       F                                  N

El Motor usa el retículo de INFORMACIÓN (≤_k) para la propagación
monotónica:

    N  <_k  V
    N  <_k  F
    V  <_k  B
    F  <_k  B

Principio de monotonía: el conjunto admisible solo puede REDUCIRSE a lo
largo de una ejecución; nunca se añaden valores. Esto garantiza la
convergencia al punto fijo en un número finito de pasos, acotado por
|FOUR|² = 16.

Representación de conjuntos admisibles
---------------------------------------
Cada variable mantiene un set de candidatos ⊆ {"V", "F", "N", "B"}.
El conjunto completo {"V", "F", "N", "B"} representa ignorancia total.
El conjunto vacío {} representaría inconsistencia absoluta (no debería
ocurrir en un grafo bien formado, pero se maneja con gracia devolviendo "B").

El valor `effective` es el ínfimo (mínimo) del conjunto admisible en ≤_k:

    ínfimo({"V","F","N","B"}) = N   (mínimo información)
    ínfimo({"V"})             = V
    ínfimo({"F"})             = F
    ínfimo({"B"})             = B
    ínfimo({"V","F"})         = N   (V y F son incomparables → caemos a N)
    ínfimo({"V","B"})         = V   (V ≤_k B, el mínimo es V)
    ínfimo({"F","B"})         = F   (F ≤_k B, el mínimo es F)
    ínfimo({})                = B   (sobre-determinado por vacío)
"""

from __future__ import annotations

from typing import FrozenSet, Set

# ---------------------------------------------------------------------------
# Constantes del retículo FOUR
# ---------------------------------------------------------------------------

#: Universo completo de valores epistémicos.
FOUR: FrozenSet[str] = frozenset({"V", "F", "N", "B"})

#: Orden parcial ≤_k expresado como: INFO_ORDER[x] = conjunto de valores
#: que son ≥_k que x (es decir, x ≤_k y para todo y en INFO_ORDER[x]).
#: N ≤_k V, F, B
#: V ≤_k B
#: F ≤_k B
#: B ≤_k (nada por encima)
_INFO_ORDER_ABOVE: dict[str, FrozenSet[str]] = {
    "N": frozenset({"N", "V", "F", "B"}),   # N es el mínimo global
    "V": frozenset({"V", "B"}),
    "F": frozenset({"F", "B"}),
    "B": frozenset({"B"}),                   # B es el máximo global
}

#: Prioridad para calcular el ínfimo: menor número = menos información.
#: N(0) → V(1) = F(1) → B(2)
_INFO_RANK: dict[str, int] = {"N": 0, "V": 1, "F": 1, "B": 2}


def _infimum(admissible: Set[str]) -> str:
    """
    Calcula el ínfimo (mínimo de información) del conjunto admisible en ≤_k.

    Algoritmo O(|admissible|²): para cada candidato x, verifica si existe
    algún y en el conjunto tal que y <_k x (es decir, y tiene menos
    información que x). El ínfimo es el x para el que ningún y lo domina.

    Casos degenerados
    -----------------
    - Conjunto vacío   → "B"  (inconsistencia: todo es posible / nada es seguro)
    - Singleton {x}    → x   (trivial)
    - {"V", "F"}       → "N"  (son incomparables; el ínfimo de ambos es N)

    Parameters
    ----------
    admissible : Subconjunto no vacío de {"V", "F", "N", "B"}.

    Returns
    -------
    str
        El valor epistémico con menor información dentro del conjunto.
    """
    if not admissible:
        # Conjunto vacío ≡ sobre-determinación extrema: retornamos B
        return "B"

    # El ínfimo en ≤_k es el elemento x tal que x ≤_k y para todo y ∈ admissible.
    # Equivalentemente: x es aquel cuyo _INFO_ORDER_ABOVE[x] ⊇ admissible.
    for candidate in admissible:
        if admissible <= _INFO_ORDER_ABOVE[candidate]:
            # candidate está por debajo (o igual) de todos los demás → es el ínfimo
            return candidate

    # No existe un único mínimo (conjunto contiene V y F, que son incomparables).
    # El ínfimo de {V, F} en el retículo de información es N.
    # Para cualquier conjunto que contenga tanto V como F sin que N esté ya ahí,
    # el ínfimo cae a N.  Si también está B, da igual: N sigue siendo el mínimo.
    return "N"


# ---------------------------------------------------------------------------
# VariableState
# ---------------------------------------------------------------------------

class VariableState:
    """
    Estado en memoria de una variable lógica durante el cálculo del Motor.

    Implementa la semántica de conjuntos admisibles con restricción
    monotónica: una vez que un valor es eliminado del conjunto admisible,
    nunca regresa (principio de monotonía del retículo de información).

    Attributes
    ----------
    admissible : Set[str]
        Conjunto actual de valores epistémicos admisibles para esta variable.
        Inicia como {"V", "F", "N", "B"} (ignorancia total).
    effective : str
        Valor epistémico de reporte: ínfimo del conjunto admisible en ≤_k.
        Inicia como "N" (sin información).

    Examples
    --------
    >>> s = VariableState()
    >>> s.effective
    'N'
    >>> s.restrict({"V", "B"})   # El Motor propaga: la variable debe ser V o B
    True
    >>> s.effective
    'V'                           # ínfimo de {"V", "B"} en ≤_k
    >>> s.restrict({"V"})        # Más evidencia: debe ser exactamente V
    True
    >>> s.effective
    'V'
    >>> s.restrict({"V"})        # Sin cambio: ya era {V}
    False
    """

    __slots__ = ("admissible", "effective")

    def __init__(
        self,
        initial_value: str = "N",
    ) -> None:
        """
        Inicializa el estado con ignorancia total y el valor efectivo dado.

        Parameters
        ----------
        initial_value : str
            Valor epistémico inicial ("V", "F", "N", "B").
            El conjunto admisible inicial siempre es el universo completo FOUR;
            el `effective` se fija al valor dado y NO restringe el conjunto
            aún (el Motor hará la restricción en el primer ciclo de propagación).

        Note
        ----
        Iniciar `admissible` como FOUR completo (y no como {initial_value})
        es una decisión deliberada: permite que la propagación hacia atrás
        (backward chaining) refine el conjunto usando evidencia de otros nodos.
        Si restringiéramos aquí a {initial_value} perderíamos esa capacidad.
        El `effective` solo refleja la observación inicial del front-end.
        """
        if initial_value not in FOUR:
            raise ValueError(
                f"Valor inicial inválido: '{initial_value}'. "
                f"Debe ser uno de {sorted(FOUR)}."
            )
        # Conjunto admisible: universo completo al inicio
        self.admissible: Set[str] = set(FOUR)
        # Valor efectivo: lo que el front-end declaró inicialmente
        self.effective: str = initial_value

    # ------------------------------------------------------------------
    # Método principal: restrict
    # ------------------------------------------------------------------

    def restrict(self, allowed: Set[str]) -> bool:
        """
        Intersecta el conjunto admisible con `allowed` (restricción monotónica).

        Si la intersección reduce el conjunto, recalcula `effective` como el
        ínfimo del nuevo conjunto en el retículo de información (≤_k).

        Invariante de monotonía
        -----------------------
        `admissible` solo puede REDUCIRSE o mantenerse igual.
        Nunca se añaden valores al conjunto.

        Parameters
        ----------
        allowed : Set[str]
            Conjunto de valores que el Motor considera posibles para esta
            variable dado el contexto de propagación actual.
            Debe ser un subconjunto no vacío de {"V", "F", "N", "B"}.

        Returns
        -------
        bool
            True  → el conjunto admisible se redujo (hubo mutación de estado).
            False → el conjunto no cambió (ya era un subconjunto de `allowed`).

        Raises
        ------
        ValueError
            Si `allowed` contiene valores fuera del universo FOUR.

        Examples
        --------
        >>> s = VariableState("N")
        >>> s.restrict({"V", "F"})   # Elimina N y B del admisible
        True
        >>> s.admissible
        {'V', 'F'}
        >>> s.effective
        'N'                           # ínfimo de {V, F} incomparables = N
        >>> s.restrict({"V"})        # Ahora solo queda V
        True
        >>> s.effective
        'V'
        """
        # Validación defensiva: allowed debe ser subconjunto del universo
        invalid = allowed - FOUR
        if invalid:
            raise ValueError(
                f"restrict() recibió valores fuera del universo FOUR: {invalid}"
            )

        new_admissible: Set[str] = self.admissible & allowed

        # Si el tamaño no cambió, no hubo mutación → retornar False
        if len(new_admissible) == len(self.admissible):
            return False

        # Mutación detectada: actualizar estado
        self.admissible = new_admissible
        self.effective = _infimum(self.admissible)
        return True

    # ------------------------------------------------------------------
    # Utilidades de representación (para logging y depuración)
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        sorted_admissible = sorted(self.admissible)
        return (
            f"VariableState("
            f"effective={self.effective!r}, "
            f"admissible={sorted_admissible}"
            f")"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VariableState):
            return NotImplemented
        return self.admissible == other.admissible and self.effective == other.effective
