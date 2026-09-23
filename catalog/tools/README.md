# Tools

Funciones Python normales. Type hints, docstring y nada más: ningún import de
ADK, LangGraph ni LangChain. El envoltorio lo pone cada runtime.

## Cómo se añade una

Dejas un `.py` aquí. Eso es todo — ni paquete que tocar, ni entry point que
declarar, ni reinstalar nada. Cada función pública se publica como
`<fichero>.<funcion>`:

```
catalog/tools/finance.py  ->  finance.convert_currency
                              finance.exchange_rate
```

Y se referencia desde un agente por ese nombre, nunca por ruta de import:

```yaml
spec:
  tools:
    - ref: finance.convert_currency
```

Comprueba que se ha publicado con `agentctl components`.

La misma función queda disponible **fuera** del proceso por MCP, sin tocar nada
más: `agentctl mcp list` la enseña y `agentctl mcp serve` la sirve. Así la usan
los agentes declarativos de kagent (el `RemoteMCPServer` `catalog-tools`), que no
ejecutan código de este repositorio.

## El docstring no es un comentario

Es lo que lee el modelo para decidir si llama a la función y con qué argumentos.
Los tipos le dicen la forma; el docstring, el sentido. Un docstring vago es un
bug, y se nota en producción como una herramienta que se llama cuando no toca.

```python
def convert_currency(amount: float, origen: str, destino: str) -> dict:
    """Converts an amount between two ISO-4217 currencies.

    Args:
        amount: Amount in the origin currency.
        origen: ISO-4217 code of the origin currency, e.g. "EUR".
        destino: ISO-4217 code of the destination currency, e.g. "USD".

    Returns:
        A dict with the converted amount and the rate applied.
    """
```

## Lo que no va aquí

Una función con `_` delante no se publica, y lo que importes de otro módulo
tampoco: sólo se registra lo definido en el fichero. Si prefieres ser explícito,
declara `__all__`.

Y si lo que quieres es ejecutar algo del mundo exterior —una API, un sistema de
ficheros, una base de datos— casi siempre existe ya un servidor MCP que lo hace
mejor que una función aquí dentro. Esta carpeta es para lógica propia.
