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

Open <http://127.0.0.1:8000/>. The <http://127.0.0.1:8000/health> endpoint returns
`{"status":"ok"}` while the API is reachable. Choose one input, select PDF or DOCX and PNG or SVG, then click
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
and requests a compact, evidence-backed architecture response. Set `OLLAMA_HOST`
and `OLLAMA_MODEL` as needed. On an 8 GB CPU computer, if `llama3.2:3b` cannot load, run
`ollama pull llama3.2:1b`, then in PowerShell run `$env:OLLAMA_MODEL = "llama3.2:1b"` and
restart CIAO; the application does not switch models silently.

## Generation performance and cache

Each website generation makes one Ollama call for its concise architecture summary; the
diagram itself is built deterministically from the extracted repository graph. If the model
returns an invalid shape, CIAO retries once with the specific validation issue and reports
the final reason so the failure can be diagnosed. `CIAO_TIMING` log entries show graph
analysis and each output-rendering stage.

The Ollama request uses a 4,096-token context and 1,024-token response limit. Set
`CIAO_ARCHITECTURE_CONTEXT_CHARS` to control the maximum source-evidence text supplied to the
architecture prompt (default `12000`).

## Running the notebook in Colab

The shared Colab workflow starts Ollama, launches this FastAPI app, and exposes it through a
temporary Cloudflare tunnel. If `/content/CIAO-Code-In-Architecture-Out-main` already exists,
`git clone` will fail and the notebook will keep running whatever checkout is already there.
Update it before restarting the server:

```bash
git -C /content/CIAO-Code-In-Architecture-Out-main pull --ff-only origin main
```

Then stop the old Uvicorn process and rerun the server-start cell. Check that
`http://127.0.0.1:8000/health` returns `{"status":"ok"}` before launching the tunnel. A tunnel URL is temporary;
re-run the tunnel cell after the Colab runtime resets. If the website reports that it cannot
reach CIAO, reopen the newest tunnel URL. If generation fails with an HTTP error, inspect
`/content/ciao_server.log` for the specific model validation reason. Colab runtimes are
ephemeral, and their local Ollama server is not reachable by GitHub-hosted Actions.

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
