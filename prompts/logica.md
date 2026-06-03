# Prompts

## Promp 1
Actúa como un Arquitecto de Software Senior en Python. Estamos desarrollando el "Motor" (Backend) para el sistema EPIC Playground. Nuestra única responsabilidad es recibir un JSON, procesar la lógica y devolver el JSON modificado. Debemos usar Pydantic para validar estrictamente la entrada.

Objetivo: Generar el archivo `models/snapshot.py`.

Requisitos: 
1. Crea un Enum `EvidentialValue` para los valores: "V", "F", "N", "B". 
2. Define los modelos para la capa lógica: `LogicVariable` (id, value), `LogicRelation` (id, source, target, connective, is_contrapositive con default False) y `LogicSet`. 
3. Agrupa lo anterior en un modelo `LogicGraph`. 
4. Define los modelos para el rastro de ejecución que el Motor debe generar: `ExecutionAction` (step, variable_id, old_value, new_value, description, is_stabilized) y `ExecutionTrace` (actions, stabilized, total_iterations). 
5. Define `PlaygroundMeta` con un `max_iterations` (default 100). 
6. Crea el modelo raíz `PlaygroundSnapshot`. Debe contener `meta`, `logic`, `execution_trace` (Opcional) y un campo `visual` tipado como `Dict[str, Any]`. Nota Crítica: El campo `visual` debe aceptar cualquier estructura de diccionario sin validarla, ya que el motor debe tener "ceguera espacial" y simplemente devolver esos datos intactos al front-end.

Entregable: Solo el código en Python bien tipado para `models/snapshot.py`.

## Prompt 2
Actúa como un Arquitecto de Software Senior en Python. En el paso anterior creamos los contratos de datos en Pydantic (`models/snapshot.py`). Ahora vamos a crear el núcleo matemático puro del motor en la carpeta `core/`.
Objetivo: Generar dos archivos: `core/belnap.py` y `core/connectives.py` basados en la teoría de conjuntos admisibles (restricción monotónica) para la lógica de Belnap de 4 valores ("V", "F", "N", "B").
Requisitos para `core/belnap.py`: 
1. Crea una clase `VariableState`. Esta clase representará el estado en memoria de una variable lógica durante el cálculo. 
2. Debe inicializarse con un `admissible = {"V", "F", "N", "B"}` (un Set de Python) y un `effective = "N"`. 
3. Implementa el método `restrict(self, allowed: Set[str]) -> bool`. Este método intersectará el set `allowed` con `admissible`. Si el tamaño cambia, debe recalcular `effective` seleccionando el mínimo basado en el orden de información: N < V, F < B. (Retorna True si hubo cambio, False si no).

Requisitos para `core/connectives.py`: 
1. Importa `VariableState` de `belnap.py`. 
2. Crea una clase `ImplicationMatrix`. Su constructor debe recibir `p` (antecedente), `q` (consecuente) y `z` (resultado de la implicación), los tres de tipo `VariableState`. 
3. Implementa el método `evaluate(self) -> bool` que aplique la propagación hacia adelante (UI+) y hacia atrás (UI-) mediante restricciones de conjuntos. 
4. Regla UI+: Si `z` tiene evidencia positiva (ej. su `effective` está en {"V", "B"}) y `p.effective == "V"`, entonces fuerza `q.restrict({"V", "B"})`. 
5. Regla UI-: Si `z` tiene evidencia positiva y `q.effective == "F"`, entonces fuerza `p.restrict({"F", "B"})`. 6. Retorna `True` si alguna variable (`p`, `q`, o `z`) sufrió una mutación en sus conjuntos admisibles.

Entregable: Proporciona el código en Python para ambos archivos (`belnap.py` y `connectives.py`). Asegúrate de que no dependan de Pydantic, deben ser matemáticas puras.


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

## Prompt 4
Actúa como un Arquitecto de Software Senior en Python. Tenemos los modelos en Pydantic (`models/snapshot.py`) y el núcleo matemático (`core/belnap.py` y `core/connectives.py`). Ahora vamos a crear el servicio principal que une todo.
Objetivo: Generar el archivo `services/engine.py`.
Requisitos para `services/engine.py`: 
1. Define una función `run_propagation(snapshot: PlaygroundSnapshot) -> PlaygroundSnapshot`. 
2. Inicialización Lógica: Lee `snapshot.logic.variables`. Crea un diccionario local de objetos `VariableState` instanciados. IMPORTANTE: Aplica un `restrict` inicial a cada `VariableState` para que adopte el valor inicial que trae el JSON. Por ejemplo, si el JSON dice que la variable "p" es "V", haz `estado_p.restrict({"V"})`. 
3. Inicialización de Relaciones: Lee `snapshot.logic.relations`. Por cada relación, crea una instancia de `ImplicationMatrix`. Recuerda que una relación trazada en el editor es una afirmación de que el conectivo es verdadero, por lo tanto, crea una variable `z` virtual (representando la relación), aplícale `z.restrict({"V", "B"})` y pásala a la matriz junto con las variables `p` (source) y `q` (target). 
4. El Bucle de Estabilización: Implementa un bucle que iterará hasta un máximo de `snapshot.meta.max_iterations`. En cada paso del bucle:

* a. Guarda el valor `effective` de todas las variables antes de evaluar.*
* b. Llama a `evaluate()` en todas las matrices.*
* c. Compara los nuevos valores `effective` con los guardados. Por CADA variable que haya cambiado, crea un objeto `ExecutionAction` (step=iteracion_actual, variable_id, old_value, new_value, description="Mutación por propagación") y agrégalo al `ExecutionTrace`.*
* d. Si en un ciclo completo ninguna matriz devolvió `True` (ninguna variable mutó), el sistema se estabilizó. Rompe el bucle, marca `trace.stabilized = True` y agrega una última acción indicando el fin de la estabilización.* 5. Finalización: Actualiza los valores de `snapshot.logic.variables` con los valores `effective` finales. Inyecta el `ExecutionTrace` en `snapshot.execution_trace` y retorna el `snapshot` modificado.

Entregable: Solo el código Python limpio para `services/engine.py`. Asegúrate de importar los modelos de `models.snapshot` y las clases de `core.belnap` y `core.connectives`.

## Prompt 5
Actúa como un Arquitecto de Software Senior en Python. Ya tenemos nuestros modelos (`models/snapshot.py`), nuestro núcleo matemático (`core/`) y nuestro orquestador (`services/engine.py`). Ahora necesitamos exponer este motor como un microservicio web usando FastAPI.
Objetivo: Generar dos archivos: `api/routes.py` y `main.py`.
Requisitos para `api/routes.py`: 
1. Importa `APIRouter` de fastapi, el modelo `PlaygroundSnapshot` de `models.snapshot`, y la función `run_propagation` de `services.engine`. 
2. Crea un router y define un endpoint `POST /calcular`. 
3. El endpoint debe recibir un objeto `snapshot` de tipo `PlaygroundSnapshot`. Su única responsabilidad es llamar a `resultado = run_propagation(snapshot)` y retornar el `resultado`.

Requisitos para `main.py`: 
1. Importa `FastAPI` y `CORSMiddleware`. 
2. Instancia la aplicación FastAPI con un título descriptivo (ej. "EPIC Playground Motor API"). 
3. Configura el `CORSMiddleware` permitiendo todos los orígenes (`allow_origins=["*"]`), métodos y headers. (Esto es crítico para que el Editor, que corre en otro puerto/dominio, pueda hacer la petición sin ser bloqueado por el navegador). 
4. Incluye el router de `api.routes` en la aplicación principal. 
5. Añade un endpoint simple `GET /` que devuelva un JSON de "health check" (ej. `{"status": "online"}`).

Entregable: Solo el código Python limpio para `api/routes.py` y `main.py`. Asegúrate de que las rutas de importación coincidan con la estructura del proyecto.