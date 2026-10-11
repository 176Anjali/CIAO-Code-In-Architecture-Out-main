from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def fake_ollama_for_local_tests(monkeypatch):
    monkeypatch.setattr(
        "src.service.analysis_service.generate_architecture_spec",
        lambda graph, readme, context, evidence: {
            "title": "Test architecture",
            "system_boundary": {"id": "system", "name": context["project_name"]},
            "external_actors_or_services": [],
            "components": [
                {
                    "id": "component-test",
                    "name": "Test component",
                    "responsibility": "Represents test evidence",
                    "evidence": ["main.py:1-2"],
                }
            ],
            "relationships": [],
            "principal_flow": ["Test evidence is rendered."],
            "unknowns": ["Runtime deployment unavailable."],
        },
    )
