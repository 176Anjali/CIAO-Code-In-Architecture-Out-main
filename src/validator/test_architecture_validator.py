import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

VALIDATOR_DIR = (
    PROJECT_ROOT
    / "src"
    / "validator"
)

sys.path.insert(
    0,
    str(PROJECT_ROOT)
)

sys.path.insert(
    0,
    str(VALIDATOR_DIR)
)


from architecture_validator import (
    ArchitectureValidator
)


def main():

    print("=" * 70)
    print("STEP 7.1 - ARCHITECTURE CONSISTENCY VALIDATOR")
    print("=" * 70)

    graph_path = (
        PROJECT_ROOT
        / "output"
        / "graph"
        / "repository_graph.json"
    )

    analysis_path = (
        PROJECT_ROOT
        / "output"
        / "docs"
        / "architecture_analysis.txt"
    )

    print(
        f"\nKnowledge graph:\n{graph_path}"
    )

    print(
        f"\nArchitecture analysis:\n{analysis_path}"
    )

    if not graph_path.exists():

        print(
            "\n[FAIL] Knowledge graph not found."
        )

        return

    if not analysis_path.exists():

        print(
            "\n[FAIL] Architecture analysis not found."
        )

        return

    print(
        "\n[PASS] Knowledge graph found."
    )

    print(
        "[PASS] Architecture analysis found."
    )

    validator = ArchitectureValidator(
        graph_path=graph_path,
        analysis_path=analysis_path,
    )

    try:

        validator.load_graph()

        print(
            "[PASS] Knowledge graph loaded."
        )

        validator.load_analysis()

        print(
            "[PASS] Architecture analysis loaded."
        )

        result = validator.validate()

        validator.print_report(
            result
        )

        output_file = validator.save_report(
            result
        )

        print(
            f"\nValidation report saved to:\n"
            f"{output_file}"
        )

        print("\n" + "=" * 70)
        print("STEP 7.1 STATUS")
        print("=" * 70)

        if result["statistics"]["unsupported"] > 0:

            print(
                "COMPLETED: Unsupported claims detected."
            )

        elif result["statistics"]["requires_review"] > 0:

            print(
                "COMPLETED: Claims require architectural review."
            )

        else:

            print(
                "SUCCESS: All claims are graph-supported."
            )

    except Exception as error:

        print("\n" + "=" * 70)
        print("STEP 7.1 ERROR")
        print("=" * 70)

        print(
            type(error).__name__
        )

        print(error)


if __name__ == "__main__":
    main()