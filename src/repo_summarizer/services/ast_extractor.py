"""AST skeleton extraction — structural summary per source file."""

from __future__ import annotations

import ast
import re
import textwrap
from typing import Sequence

from repo_summarizer.domain.entities import FileSkeletonResult

_PYTHON_EXTS = frozenset({".py", ".pyw"})
_JS_TS_EXTS = frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"})

_MAX_FALLBACK_LINES = 60

_JS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+\w+", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?(?:default\s+)?function\s+\w+", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+\w+\s*=\s*(?:async\s+)?\(", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?(?:interface|type)\s+\w+", re.MULTILINE),
    re.compile(r"^\s*(?:import|require)\s*[\({]", re.MULTILINE),
]


def _extract_python_imports(tree: ast.Module) -> list[str]:
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module.split(".")[0])
    return imports


def _format_arg(arg: ast.arg) -> str:
    name = arg.arg
    if arg.annotation:
        try:
            ann = ast.unparse(arg.annotation)
        except Exception:
            ann = "..."
        return f"{name}: {ann}"
    return name


def _format_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    args_parts: list[str] = []

    for arg in node.args.args:
        args_parts.append(_format_arg(arg))

    if node.args.vararg:
        args_parts.append(f"*{_format_arg(node.args.vararg)}")

    if node.args.kwarg:
        args_parts.append(f"**{_format_arg(node.args.kwarg)}")

    args_str = ", ".join(args_parts)

    ret = ""
    if node.returns:
        try:
            ret = f" -> {ast.unparse(node.returns)}"
        except Exception:
            ret = " -> ..."

    doc = ast.get_docstring(node)
    doc_line = f'    """{doc.splitlines()[0]}"""' if doc else ""

    lines = [f"{prefix} {node.name}({args_str}){ret}:"]
    if doc_line:
        lines.append(doc_line)
    lines.append("    ...")
    return "\n".join(lines)


def _extract_python_skeleton(source: str) -> tuple[str, list[str]]:
    tree = ast.parse(source)
    imports = _extract_python_imports(tree)

    parts: list[str] = []

    doc = ast.get_docstring(tree)
    if doc:
        first_line = doc.splitlines()[0]
        parts.append(f'"""{first_line}"""')

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            cls_doc = ast.get_docstring(node)
            header = f"class {node.name}:"
            if cls_doc:
                header += f'\n    """{cls_doc.splitlines()[0]}"""'
            methods: list[str] = []
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append(textwrap.indent(_format_function(child), "    "))
            parts.append(header + ("\n" + "\n".join(methods) if methods else "\n    ..."))

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parts.append(_format_function(node))

    skeleton = "\n\n".join(parts) if parts else source[:500]
    return skeleton, imports


def _extract_js_skeleton(source: str) -> tuple[str, list[str]]:
    lines = source.splitlines()
    declarations: list[str] = []
    imports: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("import ", "const ")) and "require(" in stripped:
            imports.append(stripped)
            continue
        if stripped.startswith("import "):
            imports.append(stripped)
            continue

        for pattern in _JS_PATTERNS:
            if pattern.match(line):
                declarations.append(stripped)
                break

    skeleton = "\n".join(declarations) if declarations else "\n".join(lines[:_MAX_FALLBACK_LINES])
    return skeleton, [_parse_js_import_target(imp) for imp in imports]


def _parse_js_import_target(imp_line: str) -> str:
    match = re.search(r"""(?:from|require\()\s*['"]([^'"]+)['"]""", imp_line)
    return match.group(1) if match else imp_line


def _extract_generic_skeleton(source: str) -> tuple[str, list[str]]:
    lines = source.splitlines()
    meaningful: list[str] = []
    declaration_re = re.compile(
        r"^\s*(?:def |fn |func |class |struct |pub |package |module |"
        r"type |interface |impl |enum |#include |using |namespace )",
    )
    for line in lines[:300]:
        stripped = line.strip()
        if declaration_re.match(line) or stripped.startswith(("//", "#", "/*")):
            meaningful.append(stripped)

    if len(meaningful) < 3:
        meaningful = [l.rstrip() for l in lines[:_MAX_FALLBACK_LINES]]

    skeleton = "\n".join(meaningful)
    return skeleton, []


def _extension(path: str) -> str:
    dot = path.rfind(".")
    return path[dot:].lower() if dot != -1 else ""


def extract_skeleton(path: str, content: str) -> FileSkeletonResult:
    """Extract a structural skeleton from a source file."""
    ext = _extension(path)

    try:
        if ext in _PYTHON_EXTS:
            skeleton, imports = _extract_python_skeleton(content)
        elif ext in _JS_TS_EXTS:
            skeleton, imports = _extract_js_skeleton(content)
        else:
            skeleton, imports = _extract_generic_skeleton(content)
    except SyntaxError:
        # Fall back to raw head of file on parse failure
        skeleton = "\n".join(content.splitlines()[:_MAX_FALLBACK_LINES])
        imports = []

    return FileSkeletonResult(path=path, skeleton_text=skeleton, imports=imports)


def extract_skeletons(files: Sequence[tuple[str, str]]) -> list[FileSkeletonResult]:
    """Batch extraction over extract_skeleton."""
    return [extract_skeleton(path, content) for path, content in files]
