from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict


def _identifier(value: str, fallback: str) -> str:
    result = "".join(character if character.isalnum() else "_" for character in value)
    result = result.strip("_") or fallback
    if result[0].isdigit():
        result = f"n_{result}"
    return result[:80]


def architecture_to_plantuml(spec: Dict[str, Any]) -> str:
    """Convert the prompt-driven architecture specification to PlantUML."""
    lines = [
        "@startuml",
        f'title {str(spec.get("title") or "Evidence-backed CIAO architecture").replace(chr(10), " ").replace(chr(34), chr(39))}',
        "skinparam shadowing false",
        "skinparam componentStyle rectangle",
        "",
    ]
    declarations: Dict[str, str] = {}
    for item in [
        *(spec.get("external_actors_or_services") or []),
        *(spec.get("components") or []),
    ]:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        alias = _identifier(str(item["id"]), "node")
        if alias in declarations.values():
            alias = f"{alias}_{len(declarations) + 1}"
        declarations[str(item["id"])] = alias
        label = str(item.get("name") or item["id"]).replace('"', "'")
        kind = "actor" if item in (spec.get("external_actors_or_services") or []) else "component"
        lines.append(f'{kind} "{label}" as {alias}')

    lines.append("")
    for relationship in spec.get("relationships") or []:
        if not isinstance(relationship, dict):
            continue
        source = declarations.get(str(relationship.get("source_id")))
        target = declarations.get(str(relationship.get("target_id")))
        if not source or not target:
            continue
        label = str(relationship.get("label") or "relates to").replace('"', "'")
        lines.append(f'{source} --> {target} : "{label}"')
    lines.extend(["", "@enduml"])
    return "\n".join(lines) + "\n"


def render_plantuml(
    source: str,
    output_path: Path,
    *,
    source_path: Path | None = None,
    plantuml_jar: Path | None = None,
) -> Path:
    """Render PlantUML source to an image without exposing source as the result."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    source_file = source_path or output_path.with_suffix(".puml")
    source_file.write_text(source, encoding="utf-8")
    jar = plantuml_jar or Path(
        os.getenv("PLANTUML_JAR", r"C:\PlantUML\plantuml-1.2026.8.jar")
    )
    if not jar.exists():
        raise FileNotFoundError(
            f"PlantUML JAR not found: {jar}. Set PLANTUML_JAR to a reachable PlantUML JAR."
        )
    format_name = output_path.suffix.lower().lstrip(".")
    if format_name not in {"png", "svg"}:
        raise ValueError("PlantUML output must be PNG or SVG")
    result = subprocess.run(
        ["java", "-jar", str(jar), f"-t{format_name}", str(source_file)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"PlantUML rendering failed: {detail}")
    rendered = source_file.with_suffix(output_path.suffix)
    if not rendered.exists() or rendered.stat().st_size == 0:
        raise RuntimeError(f"PlantUML did not generate {rendered.name}")
    if rendered.resolve() != output_path.resolve():
        rendered.replace(output_path)
    return output_path