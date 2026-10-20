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

    monkeypatch.setattr(
        plantuml.subprocess,
        "run",
        lambda *args, **kwargs: type(
            "Result",
            (),
            {
                "returncode": 1,
                "stderr": "render failed",
                "stdout": "",
            },
        )(),
    )

    with pytest.raises(RuntimeError, match="rendering failed"):
        render_plantuml("@startuml\n@enduml\n", existing)

    assert existing.read_bytes() == b"previous"


def test_ollama_failure_does_not_prevent_static_outputs(tmp_path, monkeypatch):
    import src.service.analysis_service as analysis_service_module

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

    service = AnalysisService(base_dir=tmp_path)

    # Support both the current split pipeline and the older Repomix pipeline.
    patched = False
    for function_name in (
        "generate_documentation_report",
        "generate_architecture_spec",
    ):
        if hasattr(analysis_service_module, function_name):
            monkeypatch.setattr(
                analysis_service_module,
                function_name,
                fail_generation,
            )
            patched = True

    if hasattr(service, "_run_repomix_ollama"):
        monkeypatch.setattr(service, "_run_repomix_ollama", fail_generation)
        patched = True

    assert patched, "No Ollama generation integration was found to simulate a failure"

    _, document, diagram = service.generate_repository_outputs(
        repository,
        "commit",
        "pdf",
        "png",
        output,
        require_ollama=False,
    )

    assert document.exists()
    assert document.read_bytes().startswith(b"%PDF-")
    assert diagram.exists()
    assert diagram.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")