"""MIRAGE 3.0 — AST Cyclomatic Complexity Measurement & Verification Utility.

Provides an independent, deterministic AST visitor for measuring cyclomatic complexity
and method length across Git revisions and working-tree files.

Scoring Rules:
1. Base complexity = 1 for each method.
2. Increments by +1 for each control-flow and exception decision structure:
   - ast.If
   - ast.IfExp (ternary conditional expressions)
   - ast.For
   - ast.AsyncFor
   - ast.While
   - ast.ExceptHandler
   - ast.With
   - ast.AsyncWith
   - ast.Assert
3. Increments by +(len(node.values) - 1) for boolean operations (ast.BoolOp: 'and', 'or').

Usage:
    python scripts/measure_complexity.py
    python scripts/measure_complexity.py --path services/reality_verifier.py --class RealityVerifierService
    python scripts/measure_complexity.py --path services/action_governor.py --class ActionGovernorService
"""

import argparse
import ast
import subprocess


class ComplexityVisitor(ast.NodeVisitor):
    """AST NodeVisitor computing cyclomatic complexity for a Python function/method."""

    def __init__(self) -> None:
        self.complexity: int = 1

    def visit_If(self, node: ast.If) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self.complexity += len(node.values) - 1
        self.generic_visit(node)


def analyze_methods(source_text: str, target_class: str) -> dict[str, tuple[int, int, int, int]]:
    """Parse source and return {method_name: (lines, complexity, start_line, end_line)}."""
    tree = ast.parse(source_text)
    methods: dict[str, tuple[int, int, int, int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == target_class:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    vis = ComplexityVisitor()
                    for child in item.body:
                        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            vis.visit(child)
                    end = getattr(item, "end_lineno", item.lineno)
                    lines = end - item.lineno + 1
                    methods[item.name] = (lines, vis.complexity, item.lineno, end)
    return methods


def get_git_content(rev: str, path: str) -> str:
    """Fetch content of path at specific git revision."""
    res = subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True, text=True, encoding="utf-8")
    return res.stdout


def get_working_tree_content(path: str) -> str:
    """Read working-tree file content."""
    with open(path, encoding="utf-8") as f:
        return f.read()


def compare_class(
    path: str,
    class_name: str,
    base_rev: str = "51cffc0",
    r1_rev: str = "1a5b7b6",
    final_rev: str | None = None,
) -> None:
    """Compare complexity of a class across baseline, intermediate refactor, and final revisions."""
    base_src = get_git_content(base_rev, path)
    r1_src = get_git_content(r1_rev, path)
    final_src = get_git_content(final_rev, path) if final_rev else get_working_tree_content(path)

    base_m = analyze_methods(base_src, class_name)
    r1_m = analyze_methods(r1_src, class_name)
    final_m = analyze_methods(final_src, class_name)

    print(f"\n==================== {path} -> {class_name} ====================")
    all_names = sorted(set(base_m.keys()) | set(r1_m.keys()) | set(final_m.keys()))
    header = (
        f"{'Method Name':<42} | {'Base L':<7} | {'R1 L':<7} | {'Fin L':<7} | "
        f"{'Base C':<7} | {'R1 C':<7} | {'Fin C':<7} | {'Status'}"
    )
    print(header)
    print("-" * 115)
    tot_base_c = sum(m[1] for m in base_m.values())
    tot_r1_c = sum(m[1] for m in r1_m.values())
    tot_fin_c = sum(m[1] for m in final_m.values())
    tot_base_l = sum(m[0] for m in base_m.values())
    tot_r1_l = sum(m[0] for m in r1_m.values())
    tot_fin_l = sum(m[0] for m in final_m.values())

    for name in all_names:
        b_info = base_m.get(name)
        r1_info = r1_m.get(name)
        f_info = final_m.get(name)
        b_l = str(b_info[0]) if b_info else "-"
        r1_l = str(r1_info[0]) if r1_info else "-"
        f_l = str(f_info[0]) if f_info else "-"
        b_c = str(b_info[1]) if b_info else "-"
        r1_c = str(r1_info[1]) if r1_info else "-"
        f_c = str(f_info[1]) if f_info else "-"

        status = "RETAINED"
        if not b_info and not r1_info:
            status = "NEW_DECOMPOSED_HELPER"
        elif not b_info:
            status = "EXTRACTED_HELPER"
        elif not f_info:
            status = "REMOVED"
        elif f_info[1] < b_info[1]:
            status = f"REDUCED (-{b_info[1] - f_info[1]})"
        elif f_info[1] > b_info[1]:
            status = f"INCREASED (+{f_info[1] - b_info[1]})"
        print(f"{name:<42} | {b_l:<7} | {r1_l:<7} | {f_l:<7} | {b_c:<7} | {r1_c:<7} | {f_c:<7} | {status}")

    print("-" * 115)
    totals = (
        f"{'SUM OF METHOD COMPLEXITY':<42} | {tot_base_l:<7} | {tot_r1_l:<7} | "
        f"{tot_fin_l:<7} | {tot_base_c:<7} | {tot_r1_c:<7} | {tot_fin_c:<7}"
    )
    print(totals)


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure AST cyclomatic complexity across revisions.")
    parser.add_argument("--path", default=None, help="Specific file path to measure")
    parser.add_argument("--class", dest="class_name", default=None, help="Target class name")
    parser.add_argument("--base", default="51cffc0", help="Baseline git commit SHA")
    parser.add_argument("--r1", default="1a5b7b6", help="Refactor 1 git commit SHA")
    parser.add_argument("--final", default=None, help="Final git commit SHA (default: working tree)")
    args = parser.parse_args()

    if args.path and args.class_name:
        compare_class(args.path, args.class_name, args.base, args.r1, args.final)
    else:
        compare_class("services/reality_verifier.py", "RealityVerifierService", args.base, args.r1, args.final)
        compare_class("services/action_governor.py", "ActionGovernorService", args.base, args.r1, args.final)


if __name__ == "__main__":
    main()
