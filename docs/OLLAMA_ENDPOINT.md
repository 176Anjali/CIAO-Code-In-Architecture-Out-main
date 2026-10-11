# Ollama endpoint requirements

CIAO uses the existing Repomix plus `prompt.json` plus `main.py` pipeline. The
pipeline reads `OLLAMA_HOST` and `OLLAMA_MODEL`; it does not assume Google
Colab, localhost, or any other hosting environment.

For GitHub Actions, use a secured self-hosted runner on the same private
network as Ollama, or provide a secured reachable `OLLAMA_HOST` endpoint
through an Actions secret. Do not expose Ollama directly to the public
internet. Restrict access with network policy, authentication or a private
tunnel appropriate to the deployment, and install the model named by
`OLLAMA_MODEL` on the reachable Ollama service.

The workflow records the source repository, branch, triggering commit SHA and
message, generation time, and synchronization time in `ciao-generation.json`.