# CIAO — Code In, Architecture Out

CIAO is a command-line tool that uses Repomix to collect a repository snapshot and Ollama to generate an arc42-style Markdown report with PlantUML diagram definitions. It uses the local Ollama service; no OpenAI API key is required.

## Requirements

- Python 3.11 or newer
- Node.js and npm, for the Repomix command-line tool
- Ollama, with enough memory for the selected model

## Setup on Windows PowerShell

From the repository root:

```powershell
cd .\CIAO-system
python -m pip install -r requirements.txt
npm install --global repomix
ollama pull llama3.2:3b
```

Make sure Ollama is running. To use the recommended small default model and analyze a repository:

```powershell
$env:OLLAMA_MODEL = "llama3.2:3b"
python .\main.py "https://github.com/owner/repository"
```

A local repository path can be supplied instead of a GitHub URL. The generated report is written to `CIAO-system/arc42_documentation.txt`.

## Ollama settings

CIAO defaults to `llama3.2:3b`, an 8,192-token context, and at most 1,536 generated tokens per section. These limits are configurable before starting CIAO:

```powershell
$env:OLLAMA_HOST = "http://localhost:11434"
$env:OLLAMA_MODEL = "llama3.2:3b"
$env:OLLAMA_CONTEXT_SIZE = "8192"
$env:OLLAMA_INPUT_TOKEN_LIMIT = "6000"
$env:OLLAMA_MAX_OUTPUT_TOKENS = "1536"
```

The prompt asks CIAO to group related files and prioritize architecture-critical components and flows. It should state limitations when the available evidence or response budget cannot support a complete inventory.
