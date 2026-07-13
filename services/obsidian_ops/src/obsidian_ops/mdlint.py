"""Conservative, Obsidian-safe markdown normalization for agent-authored content.

Applied to notes the agent writes (not to human notes), so agent output is
consistently lint-clean without risking damage to Obsidian syntax: code
fences and YAML frontmatter pass through untouched; wikilinks, callouts,
dataview blocks and embeds are never rewritten.
"""

from __future__ import annotations

import re

_HEADING = re.compile(r"^(#{1,6})\s*(\S.*)$")


def normalize_markdown(text: str) -> str:
    lines = text.split("\n")
    out: list[str] = []
    in_fence = False
    fence_marker = ""
    index = 0

    # pass frontmatter through untouched
    if lines and lines[0].strip() == "---":
        out.append(lines[0])
        index = 1
        while index < len(lines):
            out.append(lines[index])
            if lines[index].strip() == "---":
                index += 1
                break
            index += 1

    after_heading = False
    for line in lines[index:]:
        fence = re.match(r"^(\s*)(```+|~~~+)", line)
        if in_fence:
            out.append(line)
            if fence and fence.group(2).startswith(fence_marker):
                in_fence = False
            continue
        stripped = line.rstrip()
        if fence:
            if after_heading:
                out.append("")
                after_heading = False
            in_fence = True
            fence_marker = fence.group(2)
            out.append(stripped)
            continue
        if stripped == "":
            after_heading = False
            if out and out[-1] != "":
                out.append("")
            continue
        heading = _HEADING.match(stripped)
        if heading:
            stripped = f"{heading.group(1)} {heading.group(2)}"
            if out and out[-1] != "":
                out.append("")
            out.append(stripped)
            after_heading = True
            continue
        if after_heading:
            out.append("")
            after_heading = False
        out.append(stripped)

    result = "\n".join(out).strip("\n")
    return result + "\n"
