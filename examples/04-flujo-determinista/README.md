# 4 · Flujo determinista

El orden lo decides tú. El modelo sólo rellena los huecos.

## La idea

En el escalón 3 el modelo decidía a quién llamar y cuándo parar. Aquí no decide
nada de eso: el camino está escrito. Investigar y luego escribir, siempre, en ese
orden, una vez cada uno.

Suena a menos y es a más. Un flujo determinista se puede **reproducir**, se puede
**presupuestar** —sabes cuántas llamadas al modelo va a hacer antes de
lanzarlo— y se puede **programar** en un orquestador, porque alguien de fuera
puede leer el grafo sin ejecutarlo.

Casi siempre que un sistema agéntico se descontrola es porque estaba en el
escalón 3 y su sitio era este.

## En la plataforma

[`workflows/research-and-write.yaml`](../../workflows/research-and-write.yaml):

```yaml
spec:
  type: sequential
  nodes:
    - name: research
      agent: researcher
    - name: write
      agent: writer
```

Cuatro formas: `sequential` en línea, `parallel` en abanico, `loop` repitiendo
con tope, y `graph` con las aristas escritas a mano.

Y los mismos agentes sirven sueltos y como pasos. `researcher` no sabe que forma
parte de un flujo, que es justo lo que permite reusarlo en otro.

```bash
agentctl run research-and-write -m "arquitectura hexagonal"
agentctl --runtime langgraph run research-and-write -m "arquitectura hexagonal"
```

### La forma publicada

Al publicar, lo implícito se escribe:

```bash
agentctl export research-and-write -o dist/contracts
```

```yaml
nodes:
  - name: research
    agent: researcher@0.1.0          # versión fijada
    needs: []
    with: {message: "{{ inputs.message }}"}
  - name: write
    agent: writer@0.1.0
    needs: [research]                # el orden, ya explícito
    with: {input: "{{ steps.research.output }}"}
```

Mismo `kind`, mismo esquema. Es el mismo documento con las respuestas rellenadas,
y es lo que lee un orquestador que no tiene por qué saber qué significa
`sequential`.

## A mano

- [`en_adk.py`](en_adk.py) — `Workflow` con aristas explícitas y `START`.
- [`en_langgraph.py`](en_langgraph.py) — `StateGraph`. Es el que más se parece al
  manifiesto: nodos y aristas, igual que el YAML.
- [`en_langchain.py`](en_langchain.py) — LCEL, `paso1 | paso2`. Encadena bien,
  pero **no** sabe de grafos arbitrarios ni de bucles: para eso hay que subirse a
  LangGraph o a ADK.

## Lo que conviene llevarse

Entre el escalón 3 y el 4 no hay una respuesta correcta: hay una pregunta. ¿El
camino depende de lo que pregunte el usuario? Entonces 3. ¿Ya lo sabes tú?
Entonces 4, y te ahorras la mitad de los problemas.
