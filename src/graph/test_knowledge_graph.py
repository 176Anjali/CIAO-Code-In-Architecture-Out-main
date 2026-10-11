import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GRAPH_DIR = PROJECT_ROOT / "src" / "graph"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if str(GRAPH_DIR) not in sys.path:
    sys.path.insert(0, str(GRAPH_DIR))

from knowledge_graph import RepositoryKnowledgeGraph


def has_edge(graph, source, relationship, target):
    return any(
        edge["source"] == source
        and edge["relationship"] == relationship
        and edge["target"] == target
        for edge in graph["edges"]
    )


def main():
    print("=" * 70)
    print("STEP 7.3 - IMPORT RESOLUTION TEST")
    print("=" * 70)

    repository_path = PROJECT_ROOT / "data" / "test_repo"

    graph_builder = RepositoryKnowledgeGraph(repository_path)
    graph = graph_builder.build()

    graph_builder.print_graph()

    app_file = (repository_path / "app.py").resolve()
    service_file = (repository_path / "service.py").resolve()

    app_node = f"file:{app_file}"
    service_node = f"file:{service_file}"
    service_class = "class:Service"
    service_method = "method:Service.process"
    service_variable = f"variable:{app_file}:service"

    print("\n" + "=" * 70)
    print("VALIDATION")
    print("=" * 70)

    failures = 0
    node_ids = {item["id"] for item in graph["nodes"]}

    for node in [
        app_node,
        service_node,
        service_class,
        service_method,
        service_variable,
    ]:
        if node in node_ids:
            print(f"[PASS] Node exists: {node}")
        else:
            print(f"[FAIL] Missing node: {node}")
            failures += 1

    checks = [
        (
            app_node,
            "IMPORTS_FILE",
            service_node,
            "[PASS] app.py --IMPORTS_FILE--> service.py",
            "[FAIL] Missing IMPORTS_FILE relationship",
        ),
        (
            app_node,
            "IMPORTS_CLASS",
            service_class,
            "[PASS] app.py --IMPORTS_CLASS--> Service",
            "[FAIL] Missing IMPORTS_CLASS relationship",
        ),
        (
            service_variable,
            "INSTANCE_OF",
            service_class,
            "[PASS] service --INSTANCE_OF--> Service",
            "[FAIL] Missing INSTANCE_OF relationship",
        ),
        (
            service_variable,
            "CALLS",
            service_method,
            "[PASS] service --CALLS--> Service.process",
            "[FAIL] Missing CALLS relationship",
        ),
        (
            service_class,
            "DEFINES",
            service_method,
            "[PASS] Service --DEFINES--> Service.process",
            "[FAIL] Missing DEFINES relationship",
        ),
        (
            app_node,
            "CALLS",
            service_method,
            "[PASS] app.py --CALLS--> Service.process",
            "[FAIL] Missing app.py CALLS relationship",
        ),
    ]

    for source, relationship, target, ok, fail in checks:
        if has_edge(graph, source, relationship, target):
            print(ok)
        else:
            print(fail)
            failures += 1

    print("\n" + "=" * 70)
    print("STEP 7.3 STATUS")
    print("=" * 70)

    if failures == 0:
        print("SUCCESS: Import and relationship resolution completed.")
    else:
        print(f"FAILED: {failures} validation checks failed.")


if __name__ == "__main__":
    main()
