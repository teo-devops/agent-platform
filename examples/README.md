# La escalera

Cuatro escalones. Cada uno añade **una** idea a la anterior, y cada uno está
resuelto dos veces: como manifiesto declarativo de esta plataforma, y a mano en
el idioma nativo de ADK, LangGraph y LangChain.

Esa duplicación es deliberada. Un manifiesto te enseña a usar la plataforma; el
código nativo te enseña el framework. Si sólo tienes lo primero, un día te toca
depurar dentro del framework y no sabes por dónde entrar.

| # | Escalón | La idea nueva | En la plataforma |
|---|---------|---------------|------------------|
| 1 | [Agente simple](01-agente-simple/) | Un modelo con instrucciones | `agents/greeting` |
| 2 | [Tools](02-tools/) | El modelo llama a tu código | `agents/health-advisor` |
| 3 | [Multi-agente](03-multi-agente/) | Un agente delega en otros | `agents/software-manager` |
| 4 | [Flujo determinista](04-flujo-determinista/) | El orden lo decides tú, no el modelo | `workflows/research-and-write` |

El salto interesante es el 3→4. En el 3 es el **modelo** quien decide a quién
llamar y cuándo parar; en el 4 lo decides **tú** y el modelo sólo rellena los
huecos. Casi siempre que un flujo agéntico se va de las manos es porque estaba
en el escalón 3 cuando debía estar en el 4.

## Cómo se ejecutan

Los manifiestos, con la plataforma:

```bash
agentctl run greeting -m "hola"
agentctl --runtime langgraph run greeting -m "hola"    # el mismo manifiesto
```

El código nativo, directamente:

```bash
python examples/01-agente-simple/en_adk.py
python examples/01-agente-simple/en_langgraph.py
python examples/01-agente-simple/en_langchain.py
```

Todos necesitan `GOOGLE_API_KEY` **exportada** en el entorno. A diferencia de
`agentctl`, el código nativo no lee el `.env`: `set -a; source .env; set +a`. Los ficheros se
llaman `en_<framework>.py` y no `<framework>.py` a propósito: un módulo llamado
`langgraph.py` tapa al paquete `langgraph` en cuanto lo ejecutas.

## Qué framework elegir

| | ADK | LangGraph | LangChain |
|---|---|---|---|
| Un agente con tools | ✅ | ✅ | ✅ |
| Delegación por herramienta | ✅ | ✅ | ✅ |
| El padre cede el turno al hijo | ✅ nativo | ❌ | ❌ |
| Flujo en línea o en abanico | ✅ | ✅ | ✅ |
| Grafo arbitrario | ✅ | ✅ | ❌ LCEL son cadenas |
| Bucle con condición de parada | ✅ | ✅ | ❌ |
| Playground local completo | ✅ `adk web` | ⚠️ API local, UI remota | ⚠️ igual que LangGraph |

La tabla no dice cuál es mejor: dice qué te va a bloquear. Si tu caso está en una
fila con ❌, ya sabes por dónde no ir.
