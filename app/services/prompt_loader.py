from __future__ import annotations

from pathlib import Path


class PromptBundle:
    def __init__(self, system: str, user_template: str) -> None:
        self.system = system
        self.user_template = user_template


def load_prompt(path: Path) -> PromptBundle:
    """Load a prompt markdown file and extract system + user template sections."""

    text = path.read_text(encoding="utf-8")
    # Minimal parsing: split by headings used in provided prompt files
    # We only need the "System Prompt" paragraph and the fenced template block under "User Prompt Template".
    system_marker = "## System Prompt"
    user_marker = "## User Prompt Template"
    sys_idx = text.find(system_marker)
    user_idx = text.find(user_marker)
    if sys_idx == -1 or user_idx == -1:
        raise ValueError(f"Prompt file missing required sections: {path}")

    system_section = text[sys_idx + len(system_marker) : user_idx].strip()

    # Extract first fenced block after User Prompt Template
    after_user = text[user_idx + len(user_marker) :]
    fence = "```"
    f1 = after_user.find(fence)
    f2 = after_user.find(fence, f1 + len(fence))
    f3 = after_user.find(fence, f2 + len(fence))
    if f1 == -1 or f2 == -1 or f3 == -1:
        raise ValueError(f"Prompt template fence not found: {path}")

    # f1..f2 contains optional language tag line, template starts after f2 newline
    template = after_user[f2 + len(fence) : f3].strip("\n")
    return PromptBundle(system=system_section, user_template=template.strip())

