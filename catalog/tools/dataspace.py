"""Dataspace tools: the catalogue an organisation offers to others.

A fixed list on purpose. The demo is about two agents of two organisations
talking over A2A, not about a real connector: in a real dataspace this would be
the provider's EDC catalogue, and the policy an ODRL offer.
"""

from __future__ import annotations

#: What organisation A offers. Each policy says what the data may be used for.
CATALOGUE = [
    {
        "id": "mobility-bcn-2025",
        "title": "Viajes en bicicleta compartida, Barcelona 2025",
        "topics": ["movilidad", "bicicleta", "transporte", "barcelona"],
        "policy": {"purposes": ["research", "public-sector"], "commercial": False},
    },
    {
        "id": "air-quality-cat",
        "title": "Calidad del aire por hora, estaciones de Cataluña",
        "topics": ["aire", "contaminación", "medio ambiente", "cataluña"],
        "policy": {"purposes": ["research", "public-sector", "commercial"], "commercial": True},
    },
    {
        "id": "energy-buildings",
        "title": "Consumo eléctrico de edificios públicos",
        "topics": ["energía", "consumo", "edificios", "electricidad"],
        "policy": {"purposes": ["research"], "commercial": False},
    },
]


def search_datasets(topic: str) -> dict:
    """Searches the datasets this organisation offers, with the usage policy of each.

    Args:
        topic: What the data should be about, in a word or two (e.g. "movilidad").

    Returns:
        A dict with 'datasets': each one with its 'id', 'title' and 'policy'
        (allowed 'purposes' and whether 'commercial' use is allowed). Empty if
        nothing matches.
    """
    wanted = topic.lower().strip()
    found = [
        {key: item[key] for key in ("id", "title", "policy")}
        for item in CATALOGUE
        if any(wanted in t or t in wanted for t in item["topics"]) or wanted in item["title"].lower()
    ]
    return {"datasets": found}
