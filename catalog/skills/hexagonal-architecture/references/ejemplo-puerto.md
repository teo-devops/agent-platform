# Un puerto y dos adaptadores

El puerto habla de pedidos, no de tablas:

```python
# ports/repositorio_pedidos.py
from typing import Protocol
from domain.pedido import Pedido

class RepositorioDePedidos(Protocol):
    def guardar(self, pedido: Pedido) -> None: ...
    def buscar_pendientes(self) -> list[Pedido]: ...
```

El adaptador de producción sabe de SQL; el dominio no se entera:

```python
# adapters/repositorio_postgres.py
class RepositorioPostgres:
    def __init__(self, conexion): self._conexion = conexion
    def guardar(self, pedido: Pedido) -> None: ...
    def buscar_pendientes(self) -> list[Pedido]: ...
```

Y el de los tests no necesita contenedor:

```python
# adapters/repositorio_memoria.py
class RepositorioEnMemoria:
    def __init__(self): self._pedidos: list[Pedido] = []
    def guardar(self, pedido: Pedido) -> None: self._pedidos.append(pedido)
    def buscar_pendientes(self) -> list[Pedido]:
        return [p for p in self._pedidos if p.pendiente]
```

Ninguna de las dos clases hereda del `Protocol`: basta con cumplirlo. Esa es la
razón de usar `Protocol` y no una ABC — el adaptador no tiene que importar el
puerto, así que la flecha de dependencia sigue apuntando hacia dentro.
