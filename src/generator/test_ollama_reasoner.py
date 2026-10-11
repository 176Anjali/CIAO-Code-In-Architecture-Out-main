import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

GENERATOR_DIR = PROJECT_ROOT / "src" / "generator"

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(GENERATOR_DIR))


from ollama_reasoner import OllamaArchitectureReasoner


def main():

    print("=" * 70)
    print("STEP 7 - GRAPH GUIDED OLLAMA REASONING")
    print("=" * 70)

    graph_path = (
        PROJECT_ROOT
        / "output"
        / "graph"
        / "repository_graph.json"
    )

    print(f"\nProject root:")
    print(PROJECT_ROOT)

    print(f"\nKnowledge graph:")
    print(graph_path)

    if not graph_path.exists():
        print("\n[FAIL] Knowledge graph does not exist.")
        print("Run Step 6 first.")
        return

    print("\n[PASS] Knowledge graph found.")

    reasoner = OllamaArchitectureReasoner(
        graph_path=graph_path
    )

    try:
        reasoner.load_graph()

        print("[PASS] Knowledge graph loaded.")

        prompt = reasoner.build_prompt()

        print("[PASS] Graph context converted to LLM prompt.")

        print("\n" + "-" * 70)
        print("GRAPH CONTEXT SENT TO OLLAMA")
        print("-" * 70)

        print(prompt)

        print("\n" + "-" * 70)
        print("CALLING OLLAMA")
        print("-" * 70)

        result = reasoner.analyze()

        output_file = reasoner.save_result(result)

        if output_file.exists():
            print("\n[PASS] Architecture analysis generated.")
            print("[PASS] Architecture analysis saved.")

        print("\n" + "=" * 70)
        print("STEP 7 STATUS")
        print("=" * 70)
        print("SUCCESS: Step 7 completed.")

    except Exception as error:

        print("\n" + "=" * 70)
        print("STEP 7 ERROR")
        print("=" * 70)

        print(type(error).__name__)
        print(error)

        print("\nCheck that:")
        print("1. Ollama is installed.")
        print("2. Ollama is running.")
        print("3. Your Ollama model is installed.")
        print("4. The model name is correct.")


if __name__ == "__main__":
    main()