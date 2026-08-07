#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_markdown_links.py — 离线 Markdown 链接巡检（轻量门禁）。

用途
    在打包 `.skill` 之前扫描 `skill/`、`docs/` 与仓库根目录的 Markdown 文件，
    找出所有相对 `.md` 链接的目标文件不存在或目录不存在的情况，避免
    SKILL.md 之类的发布面引用「已迁移为路由/已删除」的文件。

设计要点
    - 纯 stdlib；与 `tools/skill_eval/split_dataset.py` 一样只在仓库根目录运行。
    - 不发起网络请求；只检查本地相对路径文件是否存在。
    - 跳过 URL（http/https/mailto/…）、纯 fragment 链接（`#section`）以及
      代码块内的文本；后者常常是说明性举例，不属于真正链接。
    - 锚点仅记录在 README 中，不做 § 标题定位（Markdown 标题拼写轻微变化
      不应作为发布阻断）。

退出码
    0 — 全部链接命中
    1 — 至少一个链接指向不存在的文件
    2 — CLI 参数错误或仓库根目录不完整

示例
    python3 tools/check_markdown_links.py
    python3 tools/check_markdown_links.py --paths skill README.md
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path


# 标题：以 `^#` 开头直到行尾；最多 3 级即可识别单文件内链接。
_HREF_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_CODE_FENCE_RE = re.compile(r"^(\s*)(```|~~~)")


def _is_external_or_skip(href: str) -> bool:
    """URL、纯 fragment、邮箱、协议相对链接全部跳过。"""
    if not href:
        return True
    lowered = href.lower()
    if lowered.startswith(("http://", "https://", "mailto:", "tel:", "ftp://")):
        return True
    if href.startswith("#"):
        return True
    if href.startswith("//"):
        return True
    return False


def _strip_anchor(href: str) -> str:
    """去掉 `path#anchor` 中的锚点；空锚点不必校验。"""
    if "#" not in href:
        return href
    return href.split("#", 1)[0]


def _iter_markdown_files(roots: list[Path]) -> list[Path]:
    """递归收集所有 .md 文件。"""
    out: list[Path] = []
    for root in roots:
        if root.is_file() and root.suffix == ".md":
            out.append(root)
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # 跳过明显的运行产物与依赖目录，避免假阳。
            dirnames[:] = [
                d for d in dirnames
                if d not in {".git", "node_modules", ".venv", "venv", "workspace", "__pycache__", "dist", "build"}
            ]
            for name in filenames:
                if name.endswith(".md"):
                    out.append(Path(dirpath) / name)
    return sorted(out)


def _extract_links(md_path: Path) -> list[tuple[int, str]]:
    """逐行扫描 Markdown，提取本地相对链接 `(行号, href)`。

    代码块（被成对 ``` / ~~~ 包裹）内的内容不计入。
    """
    links: list[tuple[int, str]] = []
    try:
        text = md_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return links
    in_fence = False
    fence_marker = ""
    for lineno, line in enumerate(text.splitlines(), start=1):
        fence = _CODE_FENCE_RE.match(line)
        if fence:
            marker = fence.group(2)
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif line.lstrip().startswith(fence_marker):
                in_fence = False
                fence_marker = ""
            continue
        if in_fence:
            continue
        for match in _HREF_RE.finditer(line):
            href = match.group(1).strip()
            if _is_external_or_skip(href):
                continue
            href = _strip_anchor(href)
            if not href:
                continue
            links.append((lineno, href))
    return links


def _resolve(root: Path, source: Path, href: str) -> Path:
    """把相对 href 解析为仓库内绝对路径。"""
    if href.startswith("/"):
        # 仓库内绝对路径以仓库根为基准。
        return (root / href.lstrip("/")).resolve()
    return (source.parent / href).resolve()


def check_markdown_links(roots: list[Path], repo_root: Path) -> list[str]:
    """返回所有断链描述（`file:line: target missing`）。"""
    md_files = _iter_markdown_files(roots)
    breakage: list[str] = []
    for md_file in md_files:
        for lineno, href in _extract_links(md_file):
            target = _resolve(repo_root, md_file, href)
            if not target.exists():
                rel = md_file.relative_to(repo_root)
                breakage.append(f"{rel}:{lineno}: missing {href} -> {target}")
    return breakage


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check that local Markdown links resolve to existing files.",
    )
    parser.add_argument(
        "--paths",
        nargs="*",
        default=["skill", "docs", "README.md", "USAGE.md", "ROADMAP.md", "CHANGELOG.md"],
        help="要巡检的文件或目录（相对仓库根）。",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="仓库根路径（默认：本脚本所在目录的上一级）。",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="命中时只输出断链，不输出 PASS 摘要。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    repo_root = (args.repo_root or Path(__file__).resolve().parent.parent).resolve()
    if not repo_root.exists():
        print(f"error: repo root not found: {repo_root}", file=sys.stderr)
        return 2
    roots: list[Path] = []
    for raw in args.paths:
        path = (repo_root / raw).resolve() if not os.path.isabs(raw) else Path(raw).resolve()
        if not path.exists():
            print(f"error: path not found: {raw}", file=sys.stderr)
            return 2
        if repo_root not in path.parents and path != repo_root:
            print(f"error: path escapes repo root: {raw}", file=sys.stderr)
            return 2
        roots.append(path)
    breakage = check_markdown_links(roots, repo_root)
    if breakage:
        print("Markdown link check FAILED:", file=sys.stderr)
        for line in breakage:
            print(f"  {line}", file=sys.stderr)
        return 1
    if not args.quiet:
        files = sum(1 for r in roots for _ in _iter_markdown_files([r]))
        print(f"Markdown link check PASS: {files} files scanned, 0 broken links.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
