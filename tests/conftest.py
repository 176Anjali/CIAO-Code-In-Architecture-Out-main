from __future__ import annotations

import pytest
from src.pipeline_contract import ArtifactMetadata


@pytest.fixture(autouse=True)
def fake_ollama_for_local_tests(monkeypatch):
    from pathlib import Path
    from src.service.analysis_service import AnalysisService
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
    original_prompt_pipeline = AnalysisService._run_repomix_ollama
    def fake_prompt_pipeline(self, repository_path, project_output_dir, require_ollama=True):
        if (
            self.base_dir != Path(__file__).resolve().parents[1]
            and (self.base_dir / "main.py").exists()
            and (self.base_dir / "repomix.config.json").exists()
        ):
            return original_prompt_pipeline(
                self,
                repository_path,
                project_output_dir,
                require_ollama=require_ollama,
            )
        source = project_output_dir / "source" / "full_code.txt"
        documentation = project_output_dir / "docs" / "arc42_documentation.txt"
        source.parent.mkdir(parents=True, exist_ok=True)
        documentation.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("flattened source", encoding="utf-8")
        documentation.write_text(
            "# arc42 Architecture Documentation\n\n"
            "## 1. Introduction and Goals\n\n"
            "Test prompt-driven evidence.\n",
            encoding="utf-8",
        )
        return (
            {
                "prompt_documentation": documentation.read_text(encoding="utf-8"),
                "source_bytes": source.stat().st_size,
                "documentation_bytes": documentation.stat().st_size,
            },
            [
                ArtifactMetadata(
                    name=source.name,
                    kind="repository_snapshot",
                    path=str(source),
                    stage="source_capture",
                ),
                ArtifactMetadata(
                    name=documentation.name,
                    kind="documentation",
                    path=str(documentation),
                    stage="documentation",
                ),
            ],
        )

    monkeypatch.setattr(
        "src.service.analysis_service.AnalysisService._run_repomix_ollama",
        fake_prompt_pipeline,
    )