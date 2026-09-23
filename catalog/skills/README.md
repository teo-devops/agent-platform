# Skills

Instrucciones reutilizables que un agente carga **cuando le hacen falta**.

Una tool ejecuta algo; una skill enseña algo. Si lo que quieres es que el modelo
sepa *cómo* hacer algo —un estilo, un procedimiento, un criterio de revisión—
eso es una skill. Si lo que quieres es que *haga* algo fuera del modelo, eso es
una tool.

## Cómo se añade una

```
catalog/skills/<nombre>/
  SKILL.md              # obligatorio
  references/*.md       # opcional, se abre bajo demanda
  scripts/*.py          # opcional
```

`SKILL.md` lleva frontmatter YAML y el cuerpo en Markdown:

```markdown
---
name: hexagonal-architecture      # igual que la carpeta
version: 1.0.0
description: Puertos y adaptadores en Python — cómo aislar el dominio.
when_to_use: Escribas o revises un servicio que hable con base de datos o HTTP.
---

# El cuerpo, tan largo como haga falta
```

Y se engancha a un agente por referencia con rango de versión:

```yaml
spec:
  skills:
    - ref: hexagonal-architecture@^1.0
```

## Divulgación progresiva: por qué no va todo en el prompt

Lo obvio sería concatenar el cuerpo de cada skill al system prompt. Es caro y
empeora los resultados: tres skills de 2.000 tokens son 6.000 tokens en **cada**
llamada, se usen o no, compitiendo por la atención del modelo con lo que de
verdad le has pedido.

Así que sólo viajan siempre `name`, `description` y `when_to_use`. El cuerpo se
sirve con una herramienta:

```
prompt          <- "hexagonal-architecture: puertos y adaptadores. Úsala cuando..."
skill.read(n)   <- el cuerpo entero, si el agente decide que le hace falta
skill.open(n,f) <- un fichero de references/, si el cuerpo se lo indica
```

Por eso la `description` es el campo que más se trabaja: es lo único que el
agente ve siempre, y por tanto lo único que decide si la skill llega a usarse.
Una descripción vaga es una skill muerta.

## Versiones

El rango se comprueba al construir, y no cumplirlo es un error, no un aviso. Si
un agente pide `@^1.0` y en el catálogo hay una `2.0.0`, las instrucciones han
cambiado de forma incompatible y construir como si nada sería fingir que no.

Sube el **major** cuando cambies lo que la skill manda hacer; el **minor**
cuando añadas material sin contradecir lo anterior.
