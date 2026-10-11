from code_analyzer import CodeAnalyzer


repository_path = "."

analyzer = CodeAnalyzer(repository_path)

results = analyzer.analyze_repository()

for result in results:
    print(result)

print("\nSYMBOL INDEX:")
print(analyzer.symbol_index)