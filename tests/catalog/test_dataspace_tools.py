"""La tool de la organización A: qué ofrece y con qué política."""

from __future__ import annotations


def test_search_returns_the_policy_with_each_dataset(registries):
    search = registries.tools.get("dataspace.search_datasets")
    (found,) = search("bicicleta")["datasets"]
    assert found["id"] == "mobility-bcn-2025"
    assert found["policy"] == {"purposes": ["research", "public-sector"], "commercial": False}


def test_search_matches_the_title_too(registries):
    search = registries.tools.get("dataspace.search_datasets")
    assert [d["id"] for d in search("calidad del aire")["datasets"]] == ["air-quality-cat"]


def test_nothing_matches_is_an_empty_list_not_an_invention(registries):
    assert registries.tools.get("dataspace.search_datasets")("pizza") == {"datasets": []}
