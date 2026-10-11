from __future__ import annotations

import json
import os
import zipfile
from textwrap import wrap
from pathlib import Path
from typing import Any, Dict, List
from xml.etree import ElementTree


ARCHITECTURE_KEYS = {
    "title",
    "system_boundary",
    "external_actors_or_services",
    "components",
    "relationships",
    "principal_flow",
    "unknowns",
}


def generate_architecture_spec(
    graph: Dict[str, Any],
    *,
    readme: str,
    context: Dict[str, Any],
    evidence: str,
) -> Dict[str, Any]:
    """Ask Ollama for a validated, evidence-constrained architecture specification."""
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", os.getenv("CIAO_OLLAMA_MODEL", "llama3.2:3b"))
    target = {
        "submitted_source": context.get("submitted_source"),
        "project_name": context.get("project_name"),
        "repository_path": context.get("repository_path"),
        "branch": context.get("branch"),
        "commit_sha": context.get("commit_sha"),
        "commit_message": context.get("commit_message"),
        "generated_at": context.get("generated_at"),
        "document_format": context.get("document_format"),
        "image_format": context.get("image_format"),
    }
    context = {
        "analysis_context": target,
        "readme": readme[:6000],
        "nodes": graph.get("nodes", [])[:100],
        "edges": graph.get("edges", [])[:180],
        "target_evidence": evidence,
    }
    serialized = json.dumps(context, indent=2, ensure_ascii=False)
    max_evidence = int(os.getenv("CIAO_ARCHITECTURE_CONTEXT_CHARS", "24000"))
    serialized = serialized[:max_evidence]
    chunk_width = int(os.getenv("CIAO_ARCHITECTURE_CHUNK_CHARS", "12000"))
    max_chunks = int(os.getenv("CIAO_MAX_ARCHITECTURE_CHUNKS", "1"))
    chunks = wrap(serialized, width=chunk_width, break_long_words=False, break_on_hyphens=False) or ["{}"]
    chunks = chunks[:max_chunks]
    chunk_results = []
    from ollama import Client

    client = Client(host=host)
    system_prompt = """You are CIAO, a source-grounded software documentation and architecture analyst. The target project is the repository identified in the analysis context. CIAO is only the analyzer; do not document CIAO unless CIAO is explicitly the submitted target. Base every project claim on the supplied target-repository evidence. Cite claims with relative file paths and line ranges where available. Do not infer capabilities from filenames or common conventions. Do not invent frameworks, APIs, models, datasets, metrics, databases, pipelines, deployment, security properties, or users. Label interpretations as inferences and state “Not established by the provided repository evidence” when evidence is missing.

First identify the target project’s purpose and scope from its documentation and implementation. Then trace its actual entry points, components, APIs or interfaces, data flow, processing pipeline, integrations, configuration, tests, and deployment/CI behavior from source evidence. Distinguish documented claims from behavior verified in code.

Return only JSON for architecture_spec with these keys:
title, system_boundary, external_actors_or_services, components, relationships,
principal_flow, unknowns. Each component must have id, name, responsibility, and
evidence. Each relationship must have source_id, target_id, direction, label, and
evidence. Use empty lists and explain limitations in unknowns when evidence is insufficient.

Use the provenance values from the analysis context: submitted source, target project name, branch, full commit SHA when available, and generation date/time with timezone. Do not substitute CIAO’s own repository metadata. Return valid output matching the application schema; do not add commentary outside it. Keep the architecture concise: at most 12 components, 5 external actors or services, 16 relationships, 8 principal-flow steps, and 8 unknowns. Group related files into meaningful components instead of listing every file. Keep responsibilities to 15 words or fewer, relationship labels to 6 words or fewer, and evidence entries to one concise relative path and line range."""
    for index, chunk in enumerate(chunks[:12], 1):
        prompt = f"""Analyze chunk {index} of {len(chunks)} from this verified CIAO repository context.
Use only the supplied target-repository evidence and preserve relative paths and line ranges.
Do not document CIAO unless the analysis context explicitly identifies CIAO as the submitted target.
Do not invent users, APIs, databases, queues, deployment, security claims, or dependencies.
Clearly mark unknowns.
Return only the JSON architecture_spec object. This is a partial chunk; include only
components and relationships directly supported by this chunk. Return at most 12 components and 16 relationships. Group related files and keep all descriptions and evidence concise.

{chunk}
"""
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]
            response = _request_architecture_json(client, model=model, messages=messages)
            chunk_results.append(response)
        except Exception as exc:
            if isinstance(exc, RuntimeError) and str(exc).startswith("Ollama returned"):
                raise
            raise RuntimeError(
                f"Ollama generation failed at {host} using model {model}. "
                "Configure OLLAMA_HOST/OLLAMA_MODEL and ensure the model is reachable. "
                f"Details: {exc}"
            ) from exc
    return _merge_architecture_specs(chunk_results, context)


def _request_architecture_json(
    client: Any,
    *,
    model: str,
    messages: List[Dict[str, str]],
) -> Dict[str, Any]:
    last_error: Exception | None = None
    last_excerpt = ""
    for attempt in range(2):
        request_messages = messages
        if attempt == 1:
            request_messages = [
                *messages,
                {
                    "role": "user",
                    "content": (
                        "Correction: return only one valid JSON object matching the required "
                        "architecture_spec keys. Required top-level keys are title, "
                        "system_boundary, external_actors_or_services, components, "
                        "relationships, principal_flow, and unknowns. Do not use Markdown "
                        "fences or explanatory text. Keep the JSON concise: at most 12 components and 16 relationships, with short descriptions and evidence."
                    ),
                },
            ]
        response = client.chat(
            model=model,
            messages=request_messages,
            format="json",
            options={
                "num_ctx": 4096,
                "num_predict": int(os.getenv("CIAO_OLLAMA_NUM_PREDICT", "2048")),
                "temperature": 0,
            },
        )
        content = _response_content(response)
        last_excerpt = _safe_excerpt(content)
        try:
            return _extract_json_object(content)
        except RuntimeError as exc:
            last_error = exc
    raise RuntimeError(
        "Ollama returned an invalid architecture_spec after one correction retry. "
        f"Response excerpt: {last_excerpt or '[empty]'}"
    ) from last_error


def _response_content(response: Any) -> str:
    if hasattr(response, "message"):
        message = response.message
        if hasattr(message, "content"):
            return str(message.content or "")
    if isinstance(response, dict):
        return str(response.get("message", {}).get("content", "") or "")
    return ""


def _safe_excerpt(content: str, limit: int = 240) -> str:
    excerpt = " ".join(str(content or "").split())
    return excerpt[:limit] + ("..." if len(excerpt) > limit else "")


def generate_architecture_description(
    graph: Dict[str, Any],
    *,
    readme: str,
    context: Dict[str, Any],
    evidence: str,
) -> str:
    """Compatibility wrapper returning the structured spec as JSON text."""
    return json.dumps(
        generate_architecture_spec(graph, readme=readme, context=context, evidence=evidence),
        indent=2,
        ensure_ascii=False,
    )


def _extract_json_object(content: str) -> Dict[str, Any]:
    value = content.strip()
    if "```" in value:
        parts = [part.strip() for part in value.split("```") if part.strip()]
        value = next((part[4:].strip() for part in parts if part.startswith("json")), parts[0])
    start, end = value.find("{"), value.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError("Ollama returned architecture text instead of JSON architecture_spec")
    try:
        parsed = json.loads(value[start:end + 1])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ollama returned invalid architecture_spec JSON: {exc}") from exc
    return _validate_architecture_spec(parsed)


def _validate_architecture_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(spec, dict):
        raise RuntimeError("Architecture specification must be a JSON object")
    required = ARCHITECTURE_KEYS - {"external_actors_or_services"}
    missing = sorted(key for key in required if key not in spec)
    if missing:
        raise RuntimeError(
            "Architecture specification is missing required keys: " + ", ".join(missing)
        )
    components = spec.get("components", [])
    relationships = spec.get("relationships", [])
    if not isinstance(components, list) or not isinstance(relationships, list):
        raise RuntimeError("Architecture specification components and relationships must be lists")
    normalized_components = []
    ids = set()
    for item in components:
        if not isinstance(item, dict) or not item.get("id") or not item.get("name") or not item.get("responsibility"):
            raise RuntimeError("Every architecture component requires id, name, and responsibility")
        item = dict(item)
        item["evidence"] = _evidence_list(item.get("evidence"))
        ids.add(str(item["id"]))
        normalized_components.append(item)
    normalized_external = []
    for item in spec.get("external_actors_or_services", []) or []:
        if not isinstance(item, dict) or not item.get("id") or not item.get("name"):
            raise RuntimeError("Every external actor or service requires id and name")
        item = dict(item)
        item["evidence"] = _evidence_list(item.get("evidence"))
        ids.add(str(item["id"]))
        normalized_external.append(item)
    normalized_relationships = []
    for item in relationships:
        if not isinstance(item, dict) or not item.get("source_id") or not item.get("target_id") or not item.get("label"):
            raise RuntimeError("Every architecture relationship requires source_id, target_id, and label")
        if str(item["source_id"]) not in ids or str(item["target_id"]) not in ids:
            raise RuntimeError("Architecture relationship references an unknown component")
        item = dict(item)
        item["direction"] = item.get("direction", "forward")
        item["evidence"] = _evidence_list(item.get("evidence"))
        normalized_relationships.append(item)
    return {
        "title": str(spec.get("title") or "Evidence-backed system architecture"),
        "system_boundary": spec.get("system_boundary") or {"id": "system", "name": "Target system"},
        "external_actors_or_services": normalized_external,
        "components": normalized_components,
        "relationships": normalized_relationships,
        "principal_flow": spec.get("principal_flow") or [],
        "unknowns": spec.get("unknowns") or [],
    }


def _evidence_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value:
        return [str(value)]
    return ["Evidence reference not supplied by model"]


def _merge_architecture_specs(specs: List[Dict[str, Any]], context: Dict[str, Any]) -> Dict[str, Any]:
    if not specs:
        raise RuntimeError("Ollama returned no architecture specification")
    components: Dict[str, Dict[str, Any]] = {}
    relationships: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    external = []
    flows = []
    unknowns = []
    for spec in specs:
        for component in spec["components"]:
            components.setdefault(component["id"], component)
        for relationship in spec["relationships"]:
            key = (relationship["source_id"], relationship["target_id"], relationship["label"])
            relationships.setdefault(key, relationship)
        external.extend(spec["external_actors_or_services"])
        flows.extend(spec["principal_flow"])
        unknowns.extend(spec["unknowns"])
    return _validate_architecture_spec({
        "title": specs[0]["title"],
        "system_boundary": specs[0]["system_boundary"],
        "external_actors_or_services": external,
        "components": list(components.values()),
        "relationships": list(relationships.values()),
        "principal_flow": list(dict.fromkeys(str(item) for item in flows)),
        "unknowns": list(dict.fromkeys(str(item) for item in unknowns)),
    })


def validate_output(path: Path, fmt: str) -> None:
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"Generated {path.name} is missing or empty")
    data = path.read_bytes()
    if fmt == "pdf":
        if not data.startswith(b"%PDF-") or b"stream" not in data:
            raise RuntimeError(f"Generated {path.name} is not a valid visible PDF")
    elif fmt == "docx":
        try:
            with zipfile.ZipFile(path) as archive:
                document = archive.read("word/document.xml")
            if not document.strip() or b"<w:t" not in document:
                raise RuntimeError(f"Generated {path.name} contains no visible document text")
        except (KeyError, zipfile.BadZipFile) as exc:
            raise RuntimeError(f"Generated {path.name} is not a valid DOCX") from exc
    elif fmt == "png":
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError(f"Generated {path.name} is not a valid PNG")
        try:
            from PIL import Image

            with Image.open(path) as image:
                image.verify()
        except Exception as exc:
            raise RuntimeError(f"Generated {path.name} could not be opened as PNG") from exc
    elif fmt == "svg":
        try:
            root = ElementTree.fromstring(data)
            if root.tag.rsplit("}", 1)[-1] != "svg" or len(data) < 100:
                raise ValueError
        except Exception as exc:
            raise RuntimeError(f"Generated {path.name} is not a valid SVG") from exc
    else:
        raise ValueError(f"Unsupported output format: {fmt}")

