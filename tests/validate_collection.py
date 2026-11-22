"""Validate skill metadata and keep the install list aligned with the tree."""
import re
import sys
from collections import Counter
from pathlib import Path

from skills_ref import validate


def main():
    root = Path(__file__).resolve().parents[1]
    skills = sorted(path for path in (root / "skills").iterdir() if path.is_dir())
    problems = []
    commands = Counter(re.findall(
        r"^npx skills add SimonGFarmer/skills --skill ([a-z0-9-]+)\s*$",
        (root / "README.md").read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    ))
    if not skills:
        problems.append("No skills found.")
    expected = Counter(path.name for path in skills)
    for name in sorted(expected.keys() | commands.keys()):
        if expected[name] != commands[name]:
            problems.append(f"{name}: expected {expected[name]} README install commands, found {commands[name]}")

    for skill in skills:
        problems.extend(f"{skill.name}: {error}" for error in validate(skill))
    for doc in [root / "README.md", *(skill / "SKILL.md" for skill in skills)]:
        if not doc.exists():
            continue
        for link in re.findall(r"\]\(([^)\s]+)\)", doc.read_text(encoding="utf-8")):
            if "://" in link or link.startswith(("#", "mailto:")):
                continue
            if not (doc.parent / link.split("#", 1)[0]).exists():
                problems.append(f"{doc.relative_to(root)}: missing local link {link}")

    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print(f"Validated {len(skills)} skills, install commands, and local documentation links.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
