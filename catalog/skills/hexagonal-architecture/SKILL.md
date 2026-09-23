---
name: hexagonal-architecture
version: 1.0.0
description: Puertos y adaptadores en Python — cómo aislar el dominio de la infraestructura.
when_to_use: Escribas o revises un servicio Python que tenga que hablar con base de datos, HTTP o colas.
---

# Arquitectura hexagonal en Python

La regla es una sola: **las dependencias apuntan hacia dentro**. El dominio no
importa nada de infraestructura; la infraestructura importa del dominio.

## Las tres capas

1. **Dominio** (`domain/`) — entidades y reglas de negocio. Python puro: ni
   `requests`, ni `sqlalchemy`, ni `boto3`. Si un fichero de aquí importa algo
   de fuera, el diseño ya se rompió.
2. **Puertos** (`ports/`) — `Protocol` o ABC que declaran **lo que el dominio
   necesita**, en palabras del dominio: `RepositorioDePedidos`, no
   `ClientePostgres`.
3. **Adaptadores** (`adapters/`) — las implementaciones concretas de esos
   puertos. Aquí sí vive la librería de turno.

## Cómo se aplica al escribir

- Empieza por el dominio y los puertos. El adaptador es lo último y lo más fácil
  de cambiar.
- Un puerto se define desde la necesidad del dominio, no desde la API de la
  librería. Si tu puerto tiene un método `execute_sql`, no es un puerto: es
  Postgres con otro nombre.
- La inyección se hace en el borde (el `main`, el handler, el test). El dominio
  recibe puertos ya construidos y nunca los instancia.

## Cómo se aplica al revisar

Busca estas tres cosas, por este orden:

1. Un import de infraestructura dentro de `domain/`. Es el fallo más caro y el
   más fácil de ver.
2. Un puerto que filtra el vocabulario de la librería (`fetch_row`, `commit`,
   `bucket`). Filtra hoy, acopla mañana.
3. Un test de dominio que necesita levantar algo. Si hace falta un contenedor
   para probar una regla de negocio, las capas están mal.

## Qué NO es

No es "una carpeta por capa". Puedes tener las tres carpetas y seguir acoplado
si los puertos hablan el idioma de la base de datos. La carpeta es la
consecuencia, no la causa.
