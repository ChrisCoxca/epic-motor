
## Prompt 3
Actúa como un Arquitecto de Software Senior en Python. Tenemos los modelos en Pydantic (models/snapshot.py) y el núcleo matemático (core/belnap.py y core/connectives.py). Ahora vamos a crear el servicio principal que une todo.

Objetivo: Generar el archivo services/engine.py.

Requisitos para services/engine.py:
1. Define una función run_propagation(snapshot: PlaygroundSnapshot) -> PlaygroundSnapshot.
2. Inicialización Lógica: Lee snapshot.logic.variables. Crea un diccionario local de objetos VariableState instanciados. IMPORTANTE: Aplica un restrict inicial a cada VariableState para que adopte el valor inicial que trae el JSON. Por ejemplo, si el JSON dice que la variable "p" es "V", haz estado_p.restrict({"V"}).
3. Inicialización de Relaciones: Lee snapshot.logic.relations. Por cada relación, crea una instancia de ImplicationMatrix. Recuerda que una relación trazada en el editor es una afirmación de que el conectivo es verdadero, por lo tanto, crea una variable z virtual (representando la relación), aplícale z.restrict({"V", "B"}) y pásala a la matriz junto con las variables p (source) y q (target).
4. El Bucle de Estabilización: Implementa un bucle que iterará hasta un máximo de snapshot.meta.max_iterations. En cada paso del bucle:

a. Guarda el valor effective de todas las variables antes de evaluar.*

b. Llama a evaluate() en todas las matrices.*

c. Compara los nuevos valores effective con los guardados. Por CADA variable que haya cambiado, crea un objeto ExecutionAction (step=iteracion_actual, variable_id, old_value, new_value, description="Mutación por propagación") y agrégalo al ExecutionTrace.*

d. Si en un ciclo completo ninguna matriz devolvió True (ninguna variable mutó), el sistema se estabilizó. Rompe el bucle, marca trace.stabilized = True y agrega una última acción indicando el fin de la estabilización.*
5. Finalización: Actualiza los valores de snapshot.logic.variables con los valores effective finales. Inyecta el ExecutionTrace en snapshot.execution_trace y retorna el snapshot modificado.

Entregable: Solo el código Python limpio para services/engine.py. Asegúrate de importar los modelos de models.snapshot y las clases de core.belnap y core.connectives.