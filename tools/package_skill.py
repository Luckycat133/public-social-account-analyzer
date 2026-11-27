"""Build the public skill from the explicit distribution roots, offline."""
from pathlib import Path
import argparse
import zipfile


def package_skill(root: Path, output: Path) -> None:
    files = [root / "SKILL.md", root / "VERSION"]
    for directory in ("agents", "assets", "references", "scripts"):
        files.extend(
            path for path in (root / directory).rglob("*")
            if path.is_file() and "__pycache__" not in path.relative_to(root).parts
            and not any(part.startswith(".") for part in path.relative_to(root).parts)
            and path.suffix not in {".pyc", ".pyo"}
        )
    if any(path.is_symlink() for path in files):
        raise ValueError("skill archives do not accept symbolic links")
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            member = zipfile.ZipInfo("skill/" + path.relative_to(root).as_posix())
            member.external_attr = 0o100644 << 16
            archive.writestr(member, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    package_skill(Path(__file__).resolve().parents[1] / "skill", args.output)
