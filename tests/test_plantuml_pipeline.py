from pathlib import Path

import pytest

from src.service.plantuml import architecture_to_plantuml, render_plantuml
from src.service.ollama_generation import validate_output
from src.service.analysis_service import AnalysisService


def test_architecture_spec_is_converted_to_plantuml():
    source = architecture_to_plantuml(
        {
            "title": "Evidence test",
            "external_actors_or_services": [{"id": "client", "name": "Client"}],
            "components": [{"id": "api", "name": "API"}],
            "relationships": [
                {"source_id": "client", "target_id": "api", "label": "requests"}
            ],
        }
    )
    assert source.startswith("@startuml")
    assert 'actor "Client"' in source
    assert 'component "API"' in source
    assert "requests" in source
    assert source.endswith("@enduml\n")


def test_plantuml_png_is_rendered_and_validated(tmp_path):
    output = render_plantuml(
        architecture_to_plantuml(
            {
                "title": "Rendered",
                "components": [{"id": "api", "name": "API"}],
                "relationships": [],
            }
        ),
        tmp_path / "architecture.png",
    )
    validate_output(output, "png")
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_plantuml_failure_does_not_replace_existing_output(tmp_path, monkeypatch):
    from src.service import plantuml

    existing = tmp_path / "architecture.png"
    existing.write_bytes(b"previous")
    monkeypatch.setattr(plantuml.subprocess, "run", lambda *args, **kwargs: type(
        "Result", (), {"returncode": 1, "stderr": "render failed", "stdout": ""}
    )())
    with pytest.raises(RuntimeError, match="rendering failed"):
        render_plantuml("@startuml\n@enduml\n", existing)
    assert existing.read_bytes() == b"previous"


def test_generation_failure_preserves_existing_outputs(tmp_path, monkeypatch):
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / "main.py").write_text("print('evidence')\n", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    old_document = output / "documentation.pdf"
    old_diagram = output / "architecture.png"
    old_document.write_bytes(b"old report")
    old_diagram.write_bytes(b"old diagram")

    def fail_generation(*args, **kwargs):
        raise RuntimeError("Ollama unavailable")

    monkeypatch.setattr(
        "src.service.analysis_service.generate_architecture_spec",
        fail_generation,
    )
    service = AnalysisService(base_dir=tmp_path)
    monkeypatch.setattr(
        service,
        "_run_repomix_ollama",
        lambda *args, **kwargs: ({"prompt_documentation": ""}, []),
    )
    with pytest.raises(RuntimeError, match="Ollama unavailable"):
        service.generate_repository_outputs(
            repository,
            "commit",
            "pdf",
            "png",
            output,
            require_ollama=False,
        )
    assert old_document.read_bytes() == b"old report"
    assert old_diagram.read_bytes() == b"old diagram"