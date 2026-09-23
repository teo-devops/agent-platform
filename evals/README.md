# Evals

Medir si un cambio mejora o empeora, en vez de suponerlo.

Sin esto, cambiar un prompt es editar a ciegas: lees la respuesta nueva, te
parece mejor, y no sabes qué se rompió en los otros veinte casos. Con esto,
cambiar un prompt produce un número comparable con el de antes.

## Cómo se escribe una suite

```
evals/<objetivo>/
  dataset.yaml    # los casos: qué se pide y qué debe cumplir
  judges.yaml     # los criterios que evalúa un modelo
```

Están separados por la misma razón que el resto del repositorio separa
manifiesto y perfiles: los **casos** crecen cada vez que aparece un fallo nuevo,
y los **criterios** son estables y se comparten.

## Dos niveles, y el orden importa

**1. Aserciones deterministas** (`expect`). Sin modelo, sin red, sin
fluctuación. Gratis e instantáneas.

```yaml
expect:
  contains: ["24.2"]
  not_contains: ["inf", "nan"]
  max_chars: 600
  matches: "^\\{"
  json_valid: true
```

**2. Juez LLM** (`judge`). Sólo para lo que de verdad necesita criterio: tono,
estructura, si la respuesta se ha inventado algo.

> **Todo lo que se pueda comprobar con un `contains` va en `expect`.** Un
> `contains` no tiene falsos negativos; un juez sí, y además cuesta dinero y
> tarda. El juez es para lo que no se puede escribir como regla, no para lo que
> da pereza escribir.

## El juez es un agente más

Vive en [`catalog/agents/quality/eval-judge`](../catalog/agents/quality/eval-judge/),
se construye con la misma fábrica que todo lo demás y corre en el runtime que le
digas. No hay una superficie de protocolo nueva para esto, y el juez se versiona,
se revisa y —si hiciera falta— se evalúa como cualquier otro agente.

Su temperatura es 0 a propósito: un juez que fluctúa no sirve para comparar dos
ejecuciones, que es exactamente para lo que existe.

## Cómo se ejecuta

```bash
agentctl eval --all --check                  # valida las suites, sin ejecutar nada
agentctl eval greeting                       # todo
agentctl eval greeting --no-judge            # sólo aserciones deterministas
agentctl eval greeting --tag humo            # un subconjunto
agentctl --runtime langgraph eval greeting   # ¿se comporta igual en otro framework?
```

Devuelve `pass_at_1` y código ≠0 si no llega al umbral. Eso es lo que lo
convierte en una puerta y no en un informe que nadie mira.

### Dos puertas, no una

Evaluar un agente exige **ejecutarlo**, y ejecutarlo exige un modelo: no hay
forma de puntuar una respuesta que no existe. Así que hay dos puertas distintas:

| | Qué comprueba | ¿Clave? | Cuándo |
|---|---|---|---|
| `--check` | esquema, criterios que existen, objetivos que existen | no | cada commit |
| ejecución completa | si el agente responde bien | sí | antes de release, en nocturno |

Confundirlas sale caro en las dos direcciones: pedir clave en cada commit hace
que alguien acabe saltándose el gate, y fiarlo todo a `--check` es no medir
nada.

## Qué casos escribir

Los cuatro que de verdad pagan, por orden:

1. **Humo** — lo que usa todo el mundo. Si se rompe, se rompió algo gordo.
2. **Alucinación** — preguntas cuya respuesta correcta es "no lo sé". Un agente
   sin herramientas que se inventa un dato es el fallo más caro, porque suena
   igual de bien que la verdad.
3. **Seguridad** — inyección de prompt, fuga del system prompt, permisos.
4. **Límites** — entradas vacías, imposibles, larguísimas.

Y uno más, el que de verdad hace crecer la suite: **cada fallo que veas en
producción entra aquí como caso antes de arreglarlo.** Una suite que no crece es
una suite que ya no mide lo que duele.
