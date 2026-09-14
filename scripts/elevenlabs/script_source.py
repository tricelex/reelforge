"""Parse an exported script file into ordered chapters."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

_CHAPTER_RE = re.compile(r'^##\s*Chapter\s+(\d+)\s*:\s*(.*)$', re.MULTILINE)


@dataclass(frozen=True)
class ScriptChapter:
    """One chapter of narration text, ready for TTS."""

    idx: int
    title: str
    text: str


def load_chapters(path: Path) -> list[ScriptChapter]:
    """Load ordered chapters from a .json or .md/.txt script file."""
    if path.suffix.lower() == '.json':
        return _load_json_chapters(path)
    return _load_markdown_chapters(path)


def _load_json_chapters(path: Path) -> list[ScriptChapter]:
    """Load chapters from a JSON list of {idx, title, text} objects."""
    data = json.loads(path.read_text(encoding='utf-8'))
    return [
        ScriptChapter(
            idx=int(item['idx']),
            title=str(item.get('title', '')),
            text=str(item['text']),
        )
        for item in data
    ]


def _load_markdown_chapters(path: Path) -> list[ScriptChapter]:
    """Load chapters from '## Chapter N: Title' markdown headers.

    A file with no matching headers is treated as a single chapter.
    """
    content = path.read_text(encoding='utf-8')
    matches = list(_CHAPTER_RE.finditer(content))
    if not matches:
        text = content.strip()
        return [ScriptChapter(idx=1, title='', text=text)] if text else []

    chapters: list[ScriptChapter] = []
    for i, match in enumerate(matches):
        idx = int(match.group(1))
        title = match.group(2).strip()
        body_start = match.end()
        body_end = (
            matches[i + 1].start() if i + 1 < len(matches) else len(content)
        )
        text = content[body_start:body_end].strip()
        chapters.append(ScriptChapter(idx=idx, title=title, text=text))
    return chapters
