from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Sequence, Tuple, TypedDict, cast

import aiofiles
import tiktoken
from ollama import AsyncClient


BASE_DIR = Path(__file__).resolve().parent

CONFIG_PATH = BASE_DIR / "repomix.config.json"
MEMORY_PATH = BASE_DIR / "prompt.json"
FULL_CODE_PATH = BASE_DIR / "full_code.txt"
MD_PATH = BASE_DIR / "arc42_documentation.txt"

MODEL_NAME = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# Qwen2.5-Coder 7B is listed with a 32K context window.
# Leave some room for the generated response.
TOKEN_LIMIT = 20_000
OLLAMA_CONTEXT_SIZE = 32_768
OLLAMA_MAX_OUTPUT_TOKENS = 4_096

enc = tiktoken.get_encoding("cl100k_base")
client = AsyncClient(host=OLLAMA_HOST)


MessageParam = Mapping[str, str]


def sys_msg(content: str) -> MessageParam:
    return {"role": "system", "content": content}


def usr_msg(content: str) -> MessageParam:
    return {"role": "user", "content": content}


def asst_msg(content: str) -> MessageParam:
    return {"role": "assistant", "content": content}


class TextFormat(TypedDict):
    description: str


class TableFormat(TypedDict):
    columns: Sequence[str]
    caption: str


class DiagramFormat(TypedDict, total=False):
    type: str
    description: str


class StepsFormat(TypedDict):
    description: str


class ListFormat(TypedDict):
    items: Sequence[str]


class TreeFormat(TypedDict):
    description: str


class SectionFormat(TypedDict, total=False):
    text: TextFormat
    table: TableFormat
    diagram: DiagramFormat
    steps: StepsFormat
    list: ListFormat
    tree: TreeFormat
    examples: Dict[str, Any]


class SectionSpec(TypedDict, total=False):
    title: str
    goal: str
    format: SectionFormat
    style: str
    optional: bool
    example: Dict[str, Any]
    subsections: Dict[str, "SectionSpec"]


class GlobalGuidelines(TypedDict):
    objective: str
    formatting: Sequence[str]
    commitment: Sequence[str]
    code_analysis: str


class UserProfile(TypedDict):
    role: str
    preferred_language: str
    output_format: str
    writing_style: str
    target_audience: str
    include: Sequence[str]
    diagram_format: str


class Memory(TypedDict):
    global_guidelines: GlobalGuidelines
    md_safety: Sequence[str]
    user_profile: UserProfile
    doc_template: Dict[str, SectionSpec]


def ensure_memory_schema(raw: Mapping[str, Any]) -> Memory:
    required_top = {
        "global_guidelines",
        "md_safety",
        "user_profile",
        "doc_template",
    }
    missing = required_top.difference(raw.keys())

    if missing:
        raise KeyError(f"Missing keys in memory JSON: {missing}")

    return cast(Memory, raw)


def walk(tree: Mapping[str, SectionSpec]) -> Iterator[Tuple[str, SectionSpec]]:
    for section_id, spec in tree.items():
        if "goal" in spec:
            yield section_id, spec

        if "subsections" in spec:
            yield from walk(spec["subsections"])


def prompt_token_count(*parts: str) -> int:
    # Approximate only: cl100k_base is not Qwen's tokenizer.
    return sum(len(enc.encode(part)) for part in parts)


async def call_ollama_with_retry(
    messages: Sequence[MessageParam],
    model: str,
    *,
    max_retries: int = 3,
    initial_backoff: float = 2.0,
) -> str:
    backoff = initial_backoff

    for attempt in range(1, max_retries + 1):
        try:
            response = await client.chat(
                model=model,
                messages=list(messages),
                stream=False,
                options={
                    "num_ctx": OLLAMA_CONTEXT_SIZE,
                    "num_predict": OLLAMA_MAX_OUTPUT_TOKENS,
                },
            )

            content = response.message.content
            if not content:
                raise ValueError("Ollama returned empty content")

            return content

        except Exception as exc:
            if attempt == max_retries:
                raise

            print(
                f"⚠️ Ollama error (attempt {attempt}/{max_retries}): "
                f"{exc} Retrying in {backoff:.1f}s…"
            )
            await asyncio.sleep(backoff)
            backoff *= 2

    raise RuntimeError("Retry loop failed unexpectedly")


async def flatten_repo(repo: str) -> str:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"❌ Config file missing: {CONFIG_PATH}")

    is_remote = repo.startswith(("http://", "https://", "git@"))

    if is_remote:
        cmd = ["repomix", "--remote", repo, "-c", str(CONFIG_PATH)]
    else:
        # Resolve this before setting the subprocess working directory to BASE_DIR.
        repo_path = str(Path(repo).resolve())
        cmd = ["repomix", repo_path, "-c", str(CONFIG_PATH)]

    print(" ↪", " ".join(cmd))

    # Repomix's config writes full_code.txt using a path relative to its
    # working directory. Run it from CIAO-system so the file is created
    # beside this main.py file.
    if os.name == "nt":
        proc = await asyncio.create_subprocess_shell(
            subprocess.list2cmdline(cmd),
            cwd=str(BASE_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    else:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(BASE_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    stdout_b, stderr_b = await proc.communicate()

    if proc.returncode != 0:
        raise SystemExit(
            f"❌ Repomix error (code {proc.returncode}):\n"
            f"{stderr_b.decode(errors='replace')}\n"
            f"{stdout_b.decode(errors='replace')}"
        )

    try:
        async with aiofiles.open(FULL_CODE_PATH, "r", encoding="utf-8") as file:
            return cast(str, await file.read())
    except FileNotFoundError as exc:
        raise SystemExit(
            f"❌ Repomix did not create {FULL_CODE_PATH}: {exc}"
        ) from exc


async def generate_section(
    sid: str,
    spec: SectionSpec,
    code: str,
    profile: UserProfile,
    guidelines: GlobalGuidelines,
    md_rules: Iterable[str],
    semaphore: asyncio.Semaphore,
) -> str:
    print(f"🔄 {sid:>4} — {spec['title']}")
    start = time.perf_counter()

    system_global = f"""
ROLE : You are {profile['role']} writing for {profile['target_audience']}.

LANG : {profile['preferred_language']}

OUT : {profile['output_format']} — tone: {profile['writing_style']}

INCL : {', '.join(profile['include'])}; diagrams → {profile['diagram_format']}

OBJECTIVE

{guidelines['objective']}

FORMATTING

{'; '.join(guidelines['formatting'])}

COMMITMENTS

{'; '.join(guidelines['commitment'])}

POLICY

{guidelines['code_analysis']}
""".strip()

    system_md = "MD SAFETY\n" + "\n".join("• " + rule for rule in md_rules)

    assistant_payload = f"""
SECTION {sid} — {spec['title']}

Goal: {spec['goal']}

Required artefacts (JSON):

{json.dumps(spec.get('format', {}), indent=2)}

Style hints:

{spec.get('style', '')}

CHECKLIST

[ ] produce tables / figures / steps listed above

[ ] Write an introduction paragraph describing the purpose of the section.

[ ] Generate content in md format as described in the format field.

[ ] Derive all details from the source code; do not invent fictitious elements.

[ ] Where diagrams are expected, describe or insert PlantUML.

[ ] Ensure the section can be validated by someone familiar with the codebase.
""".strip()

    user_payload = f"### Flattened repository ###\n```plaintext\n{code}\n```"

    total_tok = prompt_token_count(
        system_global,
        system_md,
        assistant_payload,
        user_payload,
    )

    if total_tok > TOKEN_LIMIT:
        print(
            f"⚠️ Skipped {sid} "
            f"(estimated prompt {total_tok} tokens > {TOKEN_LIMIT})"
        )
        return ""

    messages: List[MessageParam] = [
        sys_msg(system_global),
        sys_msg(system_md),
        asst_msg(assistant_payload),
        usr_msg(user_payload),
    ]

    async with semaphore:
        try:
            content = await call_ollama_with_retry(messages, MODEL_NAME)
        except Exception as exc:
            print(f"❌ Ollama error in {sid}: {exc}")
            return ""

    duration = time.perf_counter() - start
    print(f"✔️ {sid} finished in {duration:.2f}s")

    return f"% {sid} — {spec['title']}\n{content}"


async def async_main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate arc42 docs via Repomix CLI and local Ollama"
    )
    parser.add_argument("repository", help="Local path or Git URL")
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=1,
        help="Maximum concurrent Ollama calls (default: 1)",
    )

    args = parser.parse_args()

    if args.max_parallel < 1:
        raise SystemExit("❌ --max-parallel must be at least 1.")

    print(f"🤖 Ollama model: {MODEL_NAME}")
    print(f"🌐 Ollama host: {OLLAMA_HOST}")
    print("🌀 Flattening repository …")

    code = await flatten_repo(args.repository)
    print(f"📄 {FULL_CODE_PATH.name} ({len(code):,} characters) ready")

    try:
        raw_memory = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"❌ Memory JSON not found: {MEMORY_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"❌ Invalid JSON in {MEMORY_PATH}: {exc}") from exc

    memory = ensure_memory_schema(raw_memory)

    guidelines = memory["global_guidelines"]
    profile = memory["user_profile"]
    template = memory["doc_template"]
    md_rules = memory["md_safety"]

    md_parts: List[str] = [" "]
    semaphore = asyncio.Semaphore(args.max_parallel)
    tasks: List[asyncio.Task[str]] = []

    for sid, spec in walk(template):
        tasks.append(
            asyncio.create_task(
                generate_section(
                    sid,
                    spec,
                    code,
                    profile,
                    guidelines,
                    md_rules,
                    semaphore,
                )
            )
        )

    start = time.perf_counter()
    print(f"[MAIN] Launching {len(tasks)} tasks...")
    sections = await asyncio.gather(*tasks)
    total_duration = time.perf_counter() - start

    print(f"[MAIN] All tasks done in {total_duration:.2f}s")

    md_parts.extend(filter(None, sections))
    md_parts.append(" ")

    async with aiofiles.open(MD_PATH, "w", encoding="utf-8") as file:
        await file.write("\n\n".join(md_parts))

    print(f"✅ Markdown written to {MD_PATH}")


async def run() -> None:
    try:
        await async_main()
    finally:
        await client.close()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nInterrupted by user.")