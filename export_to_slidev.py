from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


PRTTY_GLOB = "*.prtty"


@dataclass
class SlideElement:
    kind: str
    content: List[str] = field(default_factory=list)


@dataclass
class Slide:
    elements: List[SlideElement] = field(default_factory=list)

    def add_paragraph_line(self, text: str) -> None:
        if not text:
            return
        if self.elements and self.elements[-1].kind == "paragraph":
            self.elements[-1].content.append(text)
        else:
            self.elements.append(SlideElement("paragraph", [text]))

    def add_list_item(self, text: str) -> None:
        if not text:
            return
        if self.elements and self.elements[-1].kind == "list":
            self.elements[-1].content.append(text)
        else:
            self.elements.append(SlideElement("list", [text]))

    def add_quote_line(self, text: str) -> None:
        if not text:
            return
        if self.elements and self.elements[-1].kind == "quote":
            self.elements[-1].content.append(text)
        else:
            self.elements.append(SlideElement("quote", [text]))

    def start_code_block(self) -> SlideElement:
        element = SlideElement("code", [])
        self.elements.append(element)
        return element

    def is_empty(self) -> bool:
        return not any(el.content for el in self.elements)


@dataclass
class Context:
    kind: str
    indent: int
    element: Optional[SlideElement] = None


INLINE_TEXT_PATTERN = re.compile(r"<<")


def extract_inline_text(segment: str) -> Optional[str]:
    chunks: List[str] = []
    search_pos = 0
    while True:
        match = INLINE_TEXT_PATTERN.search(segment, search_pos)
        if match is None:
            break
        pos = match.end()
        length = len(segment)
        while pos < length and segment[pos].isspace():
            pos += 1
        if pos >= length:
            break
        if segment[pos] == '"':
            pos += 1
            buffer: List[str] = []
            while pos < length:
                char = segment[pos]
                if char == '\\' and pos + 1 < length:
                    buffer.append(segment[pos + 1])
                    pos += 2
                    continue
                if char == '"':
                    pos += 1
                    break
                buffer.append(char)
                pos += 1
            chunk = "".join(buffer).strip()
        else:
            buffer = []
            while pos < length and segment[pos] not in '<\n':
                buffer.append(segment[pos])
                pos += 1
            chunk = "".join(buffer).strip()
        if chunk and not chunk.startswith('.'):
            chunks.append(chunk)
        search_pos = pos
    if not chunks:
        return None
    return " ".join(chunks)


def sanitize_slide(slide: Slide) -> None:
    cleaned: List[SlideElement] = []
    for element in slide.elements:
        if not element.content:
            continue
        if element.kind == "code":
            cleaned.append(SlideElement("code", element.content.copy()))
            continue
        lines = [line for line in element.content if line.strip()]
        if not lines:
            continue
        if len(lines) % 2 == 0:
            midpoint = len(lines) // 2
            first_half = lines[:midpoint]
            second_half = lines[midpoint:]
            if first_half == second_half:
                lines = first_half
        unique_lines: List[str] = []
        last_line: Optional[str] = None
        for line in lines:
            if line == last_line:
                continue
            unique_lines.append(line)
            last_line = line
        if not unique_lines:
            continue
        if cleaned and cleaned[-1].kind == element.kind and cleaned[-1].content == unique_lines:
            continue
        cleaned.append(SlideElement(element.kind, unique_lines))
    slide.elements = cleaned


def render_slide(slide: Slide, *, first_slide: bool) -> str:
    parts: List[str] = []
    heading_consumed = False
    for element in slide.elements:
        content = [line for line in element.content if line.strip()]
        if not content:
            continue
        if element.kind == "paragraph":
            if not heading_consumed and content:
                heading_level = "#" if first_slide else "##"
                parts.append(f"{heading_level} {content[0]}")
                if len(content) > 1:
                    parts.append("")
                    parts.extend(content[1:])
                heading_consumed = True
            else:
                if parts and parts[-1] != "":
                    parts.append("")
                parts.extend(content)
        elif element.kind == "list":
            if parts and parts[-1] != "":
                parts.append("")
            parts.extend(f"- {item}" for item in content)
        elif element.kind == "quote":
            if parts and parts[-1] != "":
                parts.append("")
            parts.extend(f"> {line}" for line in content)
        elif element.kind == "code":
            if parts and parts[-1] != "":
                parts.append("")
            parts.append("```go")
            parts.extend(content)
            parts.append("```")
    return "\n".join(parts).strip()


def render_document(slides: List[Slide]) -> str:
    rendered_slides: List[str] = []
    for index, slide in enumerate(slides):
        sanitize_slide(slide)
        if slide.is_empty():
            continue
        slide_markdown = render_slide(slide, first_slide=index == 0)
        if slide_markdown:
            if rendered_slides:
                previous = rendered_slides[-1]
                if slide_markdown == previous:
                    continue
                prev_lines = previous.splitlines()
                current_lines = slide_markdown.splitlines()
                if len(current_lines) < len(prev_lines) and current_lines == prev_lines[:len(current_lines)]:
                    continue
            rendered_slides.append(slide_markdown)
    front_matter = """---
title: The Right Kind of Abstraction
theme: default
---"""
    body = "\n\n---\n\n".join(rendered_slides)
    return f"{front_matter}\n\n{body}\n"


def parse_prtty_files(root: Path) -> List[Slide]:
    slides: List[Slide] = []
    current_slide = Slide()
    contexts: List[Context] = []

    def close_contexts(up_to_indent: int) -> None:
        nonlocal contexts
        while contexts and up_to_indent <= contexts[-1].indent:
            contexts.pop()

    def close_slide() -> None:
        nonlocal current_slide, contexts
        close_contexts(-1)
        if not current_slide.is_empty():
            slides.append(current_slide)
        current_slide = Slide()
        contexts = []

    def add_text(text: str) -> None:
        if not text:
            return
        if contexts:
            ctx = contexts[-1]
            if ctx.kind == "code" and ctx.element is not None:
                ctx.element.content.append(text)
                return
            if ctx.kind == "list":
                current_slide.add_list_item(text)
                return
            if ctx.kind == "quote":
                current_slide.add_quote_line(text)
                return
        current_slide.add_paragraph_line(text)

    def add_code_line(line: str) -> None:
        if not contexts or contexts[-1].kind != "code" or contexts[-1].element is None:
            add_text(line)
            return
        contexts[-1].element.content.append(line)

    prtty_files = sorted(root.glob(PRTTY_GLOB))
    for file_path in prtty_files:
        with file_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.rstrip("\n")
                stripped = line.strip()
                indent = len(line) - len(stripped)

                if not stripped:
                    if contexts and contexts[-1].kind == "code" and contexts[-1].element is not None:
                        contexts[-1].element.content.append("")
                    continue

                if stripped.startswith("\\"):
                    continue

                if stripped.startswith('.'):
                    close_contexts(indent)
                    if stripped.startswith('.slide'):
                        close_slide()
                        continue
                    if stripped.startswith('.type'):
                        code_element = current_slide.start_code_block()
                        contexts.append(Context("code", indent, code_element))
                        continue
                    if stripped.startswith('.alternate'):
                        contexts.append(Context("list", indent))
                        continue
                    if stripped.startswith('.quote'):
                        contexts.append(Context("quote", indent))
                        continue

                    inline_text = extract_inline_text(stripped)
                    if inline_text:
                        add_text(inline_text)
                    continue

                if stripped.startswith('>'):
                    add_code_line(stripped.lstrip('> '))
                    continue

                inline_text = extract_inline_text(stripped)
                text_to_add = inline_text if inline_text is not None else stripped
                if contexts and contexts[-1].kind == "list" and not inline_text:
                    text_to_add = text_to_add.lstrip('- ')
                add_text(text_to_add)

        close_slide()

    return slides


def main() -> None:
    root = Path(__file__).parent
    slides = parse_prtty_files(root)
    output = render_document(slides)
    (root / "slides.md").write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
