from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple


_PLANTUML = re.compile(r"@startuml\b.*?@enduml", re.IGNORECASE | re.DOTALL)


def _command(image_format: str) -> List[str]:
    if image_format not in {"png", "svg"}:
        raise ValueError("Architecture diagram format must be png or svg")
    option = f"-t{image_format}"
    jar = os.getenv("PLANTUML_JAR")
    if not jar:
        bundled_jar = Path(__file__).resolve().parents[2] / "tools" / "plantuml.jar"
        if bundled_jar.is_file():
            jar = str(bundled_jar)
    if jar:
        java = shutil.which("java")
        if not java or not Path(jar).is_file():
            raise RuntimeError("PLANTUML_JAR requires Java and a valid JAR path")
        return [java, "-Djava.awt.headless=true", "-jar", jar, option, "-pipe"]
    executable = shutil.which("plantuml")
    if executable:
        return [executable, option, "-pipe"]
    raise RuntimeError("PlantUML is required to render the report architecture as PNG")


def render_architecture_png(markdown: str, destination: Path, image_format: str = "png") -> Tuple[str, int]:
    """Render the primary PlantUML diagram and remove every source block from the report."""
    matches = list(_PLANTUML.finditer(markdown))
    if not matches:
        raise RuntimeError("The generated arc42 report contains no PlantUML architecture diagram")
    primary = next(
        (match for match in matches if re.search(r"(?im)^\s*title\s+.*(?:architecture|component)", match.group())),
        matches[0],
    )
    completed = subprocess.run(
        _command(image_format), input=primary.group().encode("utf-8"), stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=180, check=False,
    )
    valid_output = completed.stdout.startswith(b"\x89PNG\r\n\x1a\n") if image_format == "png" else b"<svg" in completed.stdout[:500]
    if completed.returncode or not valid_output:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"PlantUML failed to render the architecture image: {detail or f'invalid {image_format.upper()}'}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(completed.stdout)
    return remove_plantuml_source(markdown, destination.name)


def remove_plantuml_source(
    markdown: str,
    image_name: str = "architecture.png",
    block_count: int | None = None,
) -> Tuple[str, int]:
    """Remove fenced or unfenced PlantUML source while preserving surrounding prose."""
    matches = list(_PLANTUML.finditer(markdown))
    result, fenced_count = _strip_fenced_plantuml(markdown, image_name)
    count = block_count if block_count is not None else (fenced_count or len(matches))
    if not matches:
        # A malformed or unclosed fenced block still must not leak source code.
        result = _PLANTUML.sub("", result)
        return result, fenced_count
    # Also handle source blocks that were emitted without Markdown fences.
    result = _PLANTUML.sub(
        "",
        result,
    )
    return result, count


def _strip_fenced_plantuml(markdown: str, image_name: str) -> Tuple[str, int]:
    lines = markdown.splitlines(keepends=True)
    output: List[str] = []
    removed = 0
    index = 0
    replacement = f"\n> Architecture diagram is provided separately as `{image_name}`.\n"
    while index < len(lines):
        if not lines[index].lstrip().startswith("```"):
            output.append(lines[index])
            index += 1
            continue

        end = index + 1
        body: List[str] = []
        closing_fence = False
        while end < len(lines) and lines[end].strip() != "```":
            # Recover from a missing closing fence if the next diagram opens.
            if lines[end].lstrip().startswith("```"):
                break
            # Some model responses omit the closing fence after a long diagram.
            # Resume the document at the next explicit section marker so that
            # the rest of the documentation is retained.
            if body and re.match(r"^\s*%\s+\d+(?:\.\d+)?\s+[—–-]", lines[end]):
                break
            body.append(lines[end])
            end += 1
        if end < len(lines) and lines[end].strip() == "```":
            closing_fence = True
        if any(re.search(r"@startuml\b", line, re.IGNORECASE) for line in body):
            output.append(replacement)
            removed += 1
            index = end + 1 if closing_fence else end
        else:
            preserve_end = end + 1 if closing_fence else end
            output.extend(lines[index:preserve_end])
            index = preserve_end
    return "".join(output), removed
