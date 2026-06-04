"""
demo_visual.py
==============
Demo visual del Motor EPIC Playground — ejecución directa sin servidor.

Uso:
    python demo_visual.py

Muestra cuatro escenarios canónicos con salida coloreada en consola:
  1. Modus Ponens   — p→q, p=V  → q debe quedar V
  2. Modus Tollens  — p→q, q=F  → p debe quedar F
  3. Cadena larga   — p→q→r→s→t, p=V → todos deben quedar V
  4. Grafo cíclico  — p→q→r→p, p=V → debe estabilizarse sin bucle infinito
"""

import sys
import time

sys.path.insert(0, ".")

from models.snapshot import (
    EvidentialValue,
    LogicGraph,
    LogicRelation,
    LogicSet,
    LogicVariable,
    PlaygroundMeta,
    PlaygroundSnapshot,
)
from services.engine import run_propagation

# ── Códigos ANSI para color en terminal ──────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"

BLACK  = "\033[30m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
MAGENTA= "\033[95m"
CYAN   = "\033[96m"
WHITE  = "\033[97m"

BG_DARK = "\033[48;5;235m"   # fondo gris muy oscuro para cajas

# ── Paleta por valor epistémico ───────────────────────────────────────────────

VALUE_COLOR = {
    "V": GREEN,       # Verdadero   — verde
    "F": RED,         # Falso       — rojo
    "N": YELLOW,      # Sin info    — amarillo
    "B": MAGENTA,     # Ambos       — magenta
}

VALUE_LABEL = {
    "V": "V (Verdadero)",
    "F": "F (Falso)",
    "N": "N (Sin info)",
    "B": "B (Ambos / Contradicción)",
}

# ── Helpers de presentación ───────────────────────────────────────────────────

def colored_value(val: str) -> str:
    """Devuelve el valor epistémico con su color ANSI."""
    c = VALUE_COLOR.get(val, WHITE)
    return f"{BOLD}{c}{val}{RESET}"


def print_separator(char: str = "─", width: int = 62) -> None:
    print(f"{DIM}{char * width}{RESET}")


def print_header(title: str, icon: str = "⚙") -> None:
    print()
    print_separator("═")
    print(f"  {BOLD}{CYAN}{icon}  {title}{RESET}")
    print_separator("═")


def print_section(label: str) -> None:
    print(f"\n  {BOLD}{WHITE}{label}{RESET}")
    print_separator("─", 50)


def print_variables(variables, label: str = "Variables") -> None:
    print(f"  {DIM}{label}:{RESET}")
    for v in variables:
        # Normalise: EvidentialValue enum → raw string "V"/"F"/"N"/"B"
        raw = v.value
        if hasattr(raw, "value"):   # is an enum
            raw = raw.value
        badge = colored_value(raw)
        label_text = VALUE_LABEL.get(raw, raw)
        print(f"    {BOLD}{WHITE}{v.id:>6}{RESET}  →  {badge}   {DIM}({label_text}){RESET}")


def print_relations(relations) -> None:
    if not relations:
        print(f"  {DIM}(sin relaciones){RESET}")
        return
    print(f"  {DIM}Relaciones:{RESET}")
    for r in relations:
        print(f"    {BOLD}{BLUE}{r.source}{RESET}  {DIM}──[{r.connective}]──▶{RESET}  {BOLD}{BLUE}{r.target}{RESET}   {DIM}(id: {r.id}){RESET}")


def print_trace(trace, max_actions: int = 20) -> None:
    """Imprime el rastro de ejecución paso a paso."""
    actions = trace.actions
    real = [a for a in actions if a.variable_id != "__system__"]
    system = [a for a in actions if a.variable_id == "__system__"]

    print(f"  {DIM}Acciones registradas: {len(real)} mutación(es){RESET}")
    print()

    shown = real[:max_actions]
    for action in shown:
        old = action.old_value.value if hasattr(action.old_value, "value") else action.old_value
        new = action.new_value.value if hasattr(action.new_value, "value") else action.new_value
        step_badge = f"{DIM}[paso {action.step:02d}]{RESET}"
        var_badge  = f"{BOLD}{WHITE}{action.variable_id}{RESET}"
        old_badge  = colored_value(old)
        new_badge  = colored_value(new)
        arrow      = f"{BOLD}{CYAN}──▶{RESET}"
        print(f"    {step_badge}  {var_badge}: {old_badge} {arrow} {new_badge}")

    if len(real) > max_actions:
        print(f"    {DIM}... ({len(real) - max_actions} acciones más omitidas){RESET}")

    print()
    if system:
        sys_action = system[0]
        print(f"  {BOLD}{GREEN}✓  {sys_action.description}{RESET}")
    else:
        print(f"  {BOLD}{YELLOW}⚠  Límite de iteraciones alcanzado (sin convergencia completa){RESET}")

    # Resumen
    stab_color = GREEN if trace.stabilized else YELLOW
    stab_text  = "ESTABILIZADO" if trace.stabilized else "LÍMITE ALCANZADO"
    print()
    print(f"  {BOLD}{stab_color}Estado final:{RESET}  {BOLD}{stab_color}{stab_text}{RESET}")
    print(f"  {DIM}Total de iteraciones:{RESET}  {BOLD}{WHITE}{trace.total_iterations}{RESET}")


def make_snapshot(variables: dict, relations: list, max_iter: int = 100,
                  visual: dict | None = None) -> PlaygroundSnapshot:
    return PlaygroundSnapshot(
        meta=PlaygroundMeta(max_iterations=max_iter),
        logic=LogicGraph(
            logic_set=LogicSet(
                variables=[LogicVariable(id=k, value=v) for k, v in variables.items()],
                relations=[
                    LogicRelation(id=r["id"], source=r["src"],
                                  target=r["tgt"], connective="IMPLIES")
                    for r in relations
                ],
            )
        ),
        visual=visual or {"demo": True},
    )


def run_scenario(title: str, icon: str, variables: dict, relations: list,
                 max_iter: int = 100, visual: dict | None = None) -> None:
    """Ejecuta un escenario y muestra el resultado completo."""

    print_header(title, icon)

    snap = make_snapshot(variables, relations, max_iter, visual)

    # ── Entrada ──────────────────────────────────────────────────────────────
    print_section("📥  ENTRADA")
    print_variables(snap.logic.logic_set.variables, "Variables iniciales")
    print()
    print_relations(snap.logic.logic_set.relations)
    print(f"\n  {DIM}max_iterations:{RESET}  {BOLD}{WHITE}{max_iter}{RESET}")

    # ── Ejecución ────────────────────────────────────────────────────────────
    print_section("⚙   EJECUCIÓN")
    t0 = time.perf_counter()
    result = run_propagation(snap)
    elapsed = (time.perf_counter() - t0) * 1000

    print_trace(result.execution_trace)

    # ── Salida ───────────────────────────────────────────────────────────────
    print_section("📤  RESULTADO FINAL")
    print_variables(result.logic.logic_set.variables, "Variables finales")

    # Verificar ceguera espacial
    visual_ok = result.visual == (visual or {"demo": True})
    visual_badge = (f"{GREEN}✓ intacto{RESET}" if visual_ok
                    else f"{RED}✗ alterado{RESET}")
    print(f"\n  {DIM}Campo visual:{RESET}  {visual_badge}")
    print(f"  {DIM}Tiempo de cálculo:{RESET}  {BOLD}{WHITE}{elapsed:.2f} ms{RESET}")


# ============================================================================
# Escenarios
# ============================================================================

def main() -> None:

    print(f"\n{BOLD}{BG_DARK}{CYAN}"
          f"  ╔══════════════════════════════════════════════════════════╗  \n"
          f"  ║       EPIC Playground — Motor Demo Visual                ║  \n"
          f"  ║       Lógica de Belnap · 4 valores · Propagación ≤_k    ║  \n"
          f"  ╚══════════════════════════════════════════════════════════╝  "
          f"{RESET}\n")

    # ── Escenario 1: Modus Ponens ─────────────────────────────────────────────
    run_scenario(
        title    = "Escenario 1 — Modus Ponens (UI+)",
        icon     = "🔵",
        variables= {"p": "V", "q": "N"},
        relations= [{"id": "r1", "src": "p", "tgt": "q"}],
    )

    # ── Escenario 2: Modus Tollens ────────────────────────────────────────────
    run_scenario(
        title    = "Escenario 2 — Modus Tollens (UI−)",
        icon     = "🔴",
        variables= {"p": "N", "q": "F"},
        relations= [{"id": "r1", "src": "p", "tgt": "q"}],
    )

    # ── Escenario 3: Cadena larga ─────────────────────────────────────────────
    run_scenario(
        title    = "Escenario 3 — Cadena de propagación  p→q→r→s→t",
        icon     = "🟢",
        variables= {"p": "V", "q": "N", "r": "N", "s": "N", "t": "N"},
        relations= [
            {"id": "r1", "src": "p", "tgt": "q"},
            {"id": "r2", "src": "q", "tgt": "r"},
            {"id": "r3", "src": "r", "tgt": "s"},
            {"id": "r4", "src": "s", "tgt": "t"},
        ],
    )

    # ── Escenario 4: Grafo cíclico ────────────────────────────────────────────
    run_scenario(
        title    = "Escenario 4 — Grafo cíclico  p→q→r→p  (garantía de terminación)",
        icon     = "🔁",
        variables= {"p": "V", "q": "N", "r": "N"},
        relations= [
            {"id": "r1", "src": "p", "tgt": "q"},
            {"id": "r2", "src": "q", "tgt": "r"},
            {"id": "r3", "src": "r", "tgt": "p"},
        ],
        max_iter = 20,
    )

    # ── Escenario 5: Ceguera espacial ─────────────────────────────────────────
    run_scenario(
        title    = "Escenario 5 — Ceguera espacial (visual intacto)",
        icon     = "👁",
        variables= {"p": "V", "q": "N"},
        relations= [{"id": "r1", "src": "p", "tgt": "q"}],
        visual   = {
            "nodes": {"p": {"x": 100, "y": 200, "color": "#00ff88"},
                      "q": {"x": 400, "y": 200, "color": "#ff4466"}},
            "edges": {"r1": {"style": "dashed", "animated": True}},
            "viewport": {"zoom": 1.5, "pan": [0, -50]},
        },
    )

    print()
    print_separator("═")
    print(f"  {BOLD}{GREEN}✓  Demo completada — todos los escenarios ejecutados correctamente{RESET}")
    print_separator("═")
    print()


if __name__ == "__main__":
    main()
