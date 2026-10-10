from __future__ import annotations

import ast
import pathlib
import sys


def collect(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def main() -> int:
    roots = [pathlib.Path("mixcore/src"), pathlib.Path("mixgateway/src")]
    issues: list[str] = []
    for root in roots:
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            used = collect(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        name = (alias.asname or alias.name).split(".")[0]
                        if name not in used:
                            issues.append(f"{path}: unused import {name}")
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        name = alias.asname or alias.name
                        if alias.name == "*" or name in used:
                            continue
                        if f'"{name}"' in source or f"'{name}'" in source or f"[{name}" in source:
                            continue
                        issues.append(f"{path}: unused import {name}")
    print("\n".join(issues) if issues else "no unused imports detected")
    return 0


if __name__ == "__main__":
    sys.exit(main())