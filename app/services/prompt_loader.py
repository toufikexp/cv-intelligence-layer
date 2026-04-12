from __future__ import annotations

from pathlib import Path


class PromptBundle:
    def __init__(self, system: str, user_template: str) -> None:
        self.system = system
        self.user_template = user_template


def load_prompt(path: Path) -> PromptBundle:
    """Load a prompt markdown file and extract system + user template sections.

    The markdown is expected to contain:
        ## System Prompt
        <one paragraph of instructions>

        ## User Prompt Template
        ```
        <template with {placeholders}>
        ```

        ## Few-Shot Examples   (optional, ignored)
    """

    text = path.read_text(encoding="utf-8")
    system_marker = "## System Prompt"
    user_marker = "## User Prompt Template"
    sys_idx = text.find(system_marker)
    user_idx = text.find(user_marker)
    if sys_idx == -1 or user_idx == -1:
        raise ValueError(f"Prompt file missing required sections: {path}")

    system_section = text[sys_idx + len(system_marker) : user_idx].strip()

    # Extract the first fenced block after "## User Prompt Template".
    # Bounds: opening fence ``` → newline → content → closing fence ```
    after_user = text[user_idx + len(user_marker) :]
    fence = "```"
    open_fence = after_user.find(fence)
    if open_fence == -1:
        raise ValueError(f"Prompt template opening fence not found: {path}")
    # Skip the rest of the opening fence line (handles ```, ```text, ```python, etc.)
    eol = after_user.find("\n", open_fence)
    content_start = eol + 1 if eol != -1 else open_fence + len(fence)
    close_fence = after_user.find(fence, content_start)
    if close_fence == -1:
        raise ValueError(f"Prompt template closing fence not found: {path}")

    template = after_user[content_start:close_fence].strip("\n")
    return PromptBundle(system=system_section, user_template=template.strip())

