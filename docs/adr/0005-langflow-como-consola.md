# 0005 · Langflow es la consola, no el motor

**Estado:** aceptada · evaluación completa en [`docs/control-plane.md`](../control-plane.md)

## Contexto

Hace falta una interfaz para manejar y controlar los agentes que vaya más allá
de LangGraph Studio (que enseña un grafo) y de la UI de kagent (que es un chat).
Langflow ofrece canvas, chat, HITL (1.11), API, disparadores y A2A en los dos
sentidos (1.11). Pero también trae su propio modelo de agente (LangChain) y
guarda los flujos en su base de datos.

## Decisión

- Langflow es la **consola y la orquestación de borde**. Llama a los agentes del catálogo **sólo por A2A**, con el nodo `A2A Agent`. No se construyen agentes ni lógica en componentes de Langflow.
- Los flujos se **generan** del catálogo (`agentctl langflow export`), con la topología de `agent_core/topology.py` y las plantillas de la instancia en marcha. El YAML es la fuente de verdad, y el flujo lo dice en su descripción.
- Un solo orquestador por flujo. Los bucles no se exportan: se invocan como un agente.
- `agent-langflow` es el único paquete que conoce Langflow, y habla con él por su API REST. Un test de fronteras lo comprueba.
- Seguridad mientras no exista la Fase 1: Langflow y los agentes sólo en loopback, versión fijada, sin auto-login y credenciales por máquina.

## Consecuencias

- Cambiar de consola es escribir otro exportador; los agentes no se enteran.
- Langflow no propaga `traceparent`, ni siquiera con su OTel activado (verificado): sus trazas, en su propio experimento de MLflow, se correlacionan con las de los agentes por agente y hora; no se unen.
- Langflow manda un `messageId` nuevo en cada llamada: la deduplicación A2A cubre nuestros reintentos, no las re-ejecuciones de Langflow.
- El HITL de Langflow sirve entre pasos; la aprobación dentro de un agente sigue pendiente (`spec.approvals`, Fase 3).
