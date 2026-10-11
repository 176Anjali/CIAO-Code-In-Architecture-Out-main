# CIAO — Code In, Architecture Out

CIAO accepts one source input and returns two evidence-based outputs: a documentation report and
an architecture diagram. The input can be a GitHub repository URL, one source file, or a ZIP
archive.

## Run the website

CIAO targets Python 3.11 or newer.

```powershell
python -m pip install -r requirements.txt
uvicorn src.api:app --reload
```

Open <http://127.0.0.1:8000/>. Choose one input, select PDF or DOCX and PNG or SVG, then click
**Generate documentation and diagram**. The page returns exactly two downloads:
`documentation.pdf` or `documentation.docx`, and `architecture.png` or `architecture.svg`.
The results also show the source name, branch, full source commit ID/message when available,
generation time with timezone, and a responsive preview of the generated architecture image.

For a single uploaded file, CIAO reports only symbols and relationships evidenced by that file.
It explicitly states that the whole project, runtime behavior, deployment, APIs, storage, and
CI/CD cannot be determined unless the submitted input contains evidence for them.

## Analysis architecture

The existing Python static-analysis pipeline remains the source of architecture evidence:
`CodeAnalyzer` parses supported Python files, `RepositoryKnowledgeGraph` records nodes and
relationships, and the output generator produces a report and a deterministic diagram. README
content and source paths are included as evidence where present. The website and GitHub sync
send the verified graph, README, configuration, and source evidence to the configured Ollama
model. The model response is included in the project-specific report; generation fails clearly
if Ollama is unavailable or returns empty content. Architecture diagrams are generated
deterministically from the validated knowledge graph, so they do not require a model call.
CIAO defaults to `llama3.2:3b` at `http://localhost:11434`, uses a 4,096-token context,
384 tokens per module-summary call, and 2,048 tokens for the final report. Set `OLLAMA_HOST`
and `OLLAMA_MODEL` as needed. On an 8 GB CPU computer, if `llama3.2:3b` cannot load, run
`ollama pull llama3.2:1b`, then in PowerShell run `$env:OLLAMA_MODEL = "llama3.2:1b"` and
restart CIAO; the application does not switch models silently.

## Generation performance and cache

The active website and GitHub sync pipeline makes one Ollama call per uncached graph-summary
chunk, followed by one final report call. At the default 12,000-character chunk target, the
exact first-run count is `number of summary chunks + 1` (for example, two chunks mean three
calls). A fully cached, unchanged input needs zero model calls; if one summary chunk changes,
CIAO recomputes that summary and the final report. The deterministic architecture renderer
makes zero Ollama calls. `CIAO_TIMING` log entries show graph analysis, each model call/cache
lookup, and each output-rendering stage.

Summary and final-report responses are cached under `.ciao-cache/`. Cache keys include the
prompt version, model name, and chunk content hash. The GitHub Actions workflow restores a
prior cache and saves the updated cache. `.gitignore` excludes this local cache from project
commits. You can configure `CIAO_OLLAMA_NUM_CTX` (default `4096`),
`CIAO_OLLAMA_SUMMARY_NUM_PREDICT` (default `384`), `CIAO_OLLAMA_NUM_PREDICT` (default
`2048`), `CIAO_OLLAMA_KEEP_ALIVE` (default `10m`), and `CIAO_SUMMARY_CHUNK_CHARS` (default
`12000`).

## GitHub synchronization

Repository owners can enable `.github/workflows/ciao-documentation.yml` in their own repository.
It runs on pushes, analyzes the triggering `GITHUB_SHA`, and updates generated files in the
repository root:

- `documentation.pdf` or `documentation.docx`
- `architecture.png` or `architecture.svg`
- `ciao-generation.json` (records the analyzed commit and selected formats)

The workflow defaults to PDF and PNG. Configure repository variables
`CIAO_DOCUMENT_FORMAT` (`pdf` or `docx`) and `CIAO_IMAGE_FORMAT` (`png` or `svg`) to change
those defaults. The workflow requires:

```yaml
permissions:
  contents: write
```

The owner must enable the workflow and grant this permission; CIAO does not claim automatic
synchronization for repositories that have not done so. Generated commits contain
`[ciao-generated]`, and the workflow skips those commits to prevent an endless loop. Only the
generated root files are staged. The workflow checks out the exact triggering commit, validates
both outputs before replacing existing root files, and leaves existing generated files unchanged
when generation or validation fails.

GitHub-hosted runners cannot reach Ollama running only on a developer's local computer. For
automatic sync, configure a secured self-hosted runner with Ollama installed, or provide a
secured endpoint through the `CIAO_OLLAMA_HOST` secret/variable and configure
`CIAO_OLLAMA_MODEL`. Do not treat sync as Ollama-enabled until a real model request has
succeeded on that runner.

## Validation

```powershell
python -m pytest -q
python -m py_compile src\api.py src\service\analysis_service.py src\service\report_generator.py
```
