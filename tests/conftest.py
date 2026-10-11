from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def fake_ollama_for_local_tests(monkeypatch):
    monkeypatch.setattr(
        "src.service.analysis_service.generate_documentation_report",
        lambda graph, readme, context: (
            "# Project Documentation\n\n## Introduction\n"
            + context["project_name"]
        ),
    )