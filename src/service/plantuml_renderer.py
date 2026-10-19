from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple


_PLANTUML = re.compile(r"@startuml\b.*?@enduml", re.IGNORECASE | re.DOTALL)
_TITLE = re.compile(r"^\s*title\s+(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def _command(image_format: str) -> List[str]:
    if image_format not in {"png", "svg"}:
        raise ValueError("Architecture diagram format must be png or svg")
    option = f"-t{image_format}"
    jar = os.getenv("PLANTUML_JAR")
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
    """Render report PlantUML and remove source blocks from the user document."""
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
    title_match = _TITLE.search(primary.group())
    title = title_match.group(1).strip().strip('"') if title_match else "Architecture diagram"
    result = markdown
    for match in reversed(matches):
        replacement = f"\n> Diagram source rendered as `{destination.name}` ({title}).\n"
        result = result[:match.start()] + replacement + result[match.end():]
    return result, len(matches)
