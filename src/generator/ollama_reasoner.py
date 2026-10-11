import json
import os
from pathlib import Path

import ollama


class OllamaArchitectureReasoner:
    """
    Uses the Repository Knowledge Graph as structured context
    for architecture reasoning.

    The LLM receives verified graph information instead of
    the complete source repository.
    """

    def __init__(
        self,
        graph_path=None,
        model=None,
    ):
        project_root = Path(__file__).resolve().parents[2]

        self.graph_path = Path(
            graph_path
            or project_root / "output" / "graph" / "repository_graph.json"
        )

        self.model = model or os.getenv(
            "CIAO_OLLAMA_MODEL",
            "llama3.2:3b"
        )

        self.graph_data = None

    def load_graph(self):
        """Load the repository knowledge graph."""

        if not self.graph_path.exists():
            raise FileNotFoundError(
                f"Knowledge graph not found: {self.graph_path}"
            )

        with open(
            self.graph_path,
            "r",
            encoding="utf-8"
        ) as file:
            self.graph_data = json.load(file)

        return self.graph_data

    def _build_graph_context(self):
        """Convert graph JSON into structured LLM context."""

        if self.graph_data is None:
            self.load_graph()

        nodes = self.graph_data.get("nodes", [])
        edges = self.graph_data.get("edges", [])

        context = []

        context.append("REPOSITORY KNOWLEDGE GRAPH")
        context.append("=" * 40)

        context.append("\nNODES:")

        for node in nodes:
            if isinstance(node, dict):
                node_id = node.get("id", "")
                node_type = node.get("type", "")

                context.append(
                    f"- {node_id} [{node_type}]"
                )

        context.append("\nRELATIONSHIPS:")

        for edge in edges:
            if isinstance(edge, dict):
                source = edge.get("source", "")
                target = edge.get("target", "")
                relationship = edge.get(
                    "relationship",
                    edge.get("type", "")
                )

                context.append(
                    f"- {source} --{relationship}--> {target}"
                )

        return "\n".join(context)

    def build_prompt(self):
        """Create the graph-guided architecture reasoning prompt."""

        graph_context = self._build_graph_context()

        prompt = f"""
You are a software architecture analysis assistant.

Your task is to infer software architecture from a
verified Repository Knowledge Graph.

IMPORTANT RULES:

1. Use ONLY information present in the knowledge graph.
2. Do not invent classes, files, methods, databases, APIs,
   services, or dependencies that are not represented.
3. Clearly distinguish observed relationships from interpretations.
4. Produce structured architecture information.
5. Keep the result suitable for later UML generation.
6. Do not generate UML code yet.
7. Do not generate source code.

Analyze the following knowledge graph:

{graph_context}

Return the result using exactly these sections:

ARCHITECTURE SUMMARY
Describe the overall architecture using only graph evidence.

COMPONENTS
List the important files, classes, modules, and methods.

DEPENDENCIES
Describe important relationships between components.

ENTRY POINTS
Identify files, classes, or functions that appear to act as
entry points based only on the graph.

CORE COMPONENTS
Identify components that appear central based on their
relationships.

ARCHITECTURAL OBSERVATIONS
Give observations supported by the graph.

UNCERTAINTIES
Mention anything that cannot be determined from the graph.
"""

        return prompt

    def analyze(self):
        """Send graph-guided architecture prompt to Ollama."""

        prompt = self.build_prompt()

        print("\n" + "=" * 70)
        print("OLLAMA ARCHITECTURE REASONING")
        print("=" * 70)

        print(f"\nModel: {self.model}")
        print(f"Graph: {self.graph_path}")

        response = ollama.chat(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a software architecture "
                        "analysis assistant. "
                        "Reason strictly from the supplied "
                        "knowledge graph."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
        )

        result = response["message"]["content"]

        print("\n" + "-" * 70)
        print("ARCHITECTURE ANALYSIS")
        print("-" * 70)
        print(result)

        return result

    def save_result(
        self,
        result,
        output_path=None,
    ):
        """Save architecture analysis."""

        project_root = Path(__file__).resolve().parents[2]

        output_file = Path(
            output_path
            or project_root
            / "output"
            / "docs"
            / "architecture_analysis.txt"
        )

        output_file.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        with open(
            output_file,
            "w",
            encoding="utf-8"
        ) as file:
            file.write(result)

        print(
            f"\nArchitecture analysis saved to:\n"
            f"{output_file}"
        )

        return output_file


def main():
    """Run graph-guided Ollama architecture analysis."""

    reasoner = OllamaArchitectureReasoner()

    reasoner.load_graph()

    result = reasoner.analyze()

    reasoner.save_result(result)

    print("\n" + "=" * 70)
    print("STEP 7 STATUS")
    print("=" * 70)
    print("SUCCESS: Knowledge Graph connected to Ollama.")


if __name__ == "__main__":
    main()