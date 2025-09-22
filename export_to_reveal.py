from __future__ import annotations

import html
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


def render_slide(slide: Slide) -> str:
    parts: List[str] = []
    heading_consumed = False
    for element in slide.elements:
        if not element.content:
            continue
        if element.kind == "paragraph":
            # Use the first line of the first paragraph as a heading for emphasis.
            if not heading_consumed:
                heading_text = html.escape(element.content[0])
                parts.append(f"<h2>{heading_text}</h2>")
                remaining = [line for line in element.content[1:] if line.strip()]
                if remaining:
                    paragraph = "<br>".join(html.escape(line) for line in remaining)
                    parts.append(f"<p>{paragraph}</p>")
                heading_consumed = True
            else:
                paragraph = "<br>".join(html.escape(line) for line in element.content if line.strip())
                if paragraph:
                    parts.append(f"<p>{paragraph}</p>")
        elif element.kind == "list":
            items = "".join(f"<li>{html.escape(item)}</li>" for item in element.content if item.strip())
            if items:
                parts.append(f"<ul>{items}</ul>")
        elif element.kind == "quote":
            quote_html = "<br>".join(html.escape(line) for line in element.content if line.strip())
            if quote_html:
                parts.append(f"<blockquote><p>{quote_html}</p></blockquote>")
        elif element.kind == "code":
            code_html = "\n".join(html.escape(line) for line in element.content)
            parts.append(f"<pre><code class=\"language-go\">{code_html}</code></pre>")
    return "\n".join(parts)


def render_document(slides: List[Slide]) -> str:
    sections = "\n".join(f"<section>\n{render_slide(slide)}\n</section>" for slide in slides if not slide.is_empty())
    template = f"""<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\">
    <title>The Right Kind of Abstraction</title>
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
    <link rel=\"stylesheet\" href=\"https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.css\">
    <link rel=\"stylesheet\" href=\"https://cdn.jsdelivr.net/npm/reveal.js@5/dist/theme/black.css\" id=\"theme\">
    <link rel=\"stylesheet\" href=\"https://cdn.jsdelivr.net/npm/reveal.js@5/plugin/highlight/monokai.css\">
    <style>
      .reveal section h2 {{
        font-size: 2.4rem;
        margin-bottom: 1rem;
      }}
      .reveal section p {{
        font-size: 1.25rem;
        line-height: 1.6;
      }}
      .reveal section ul {{
        font-size: 1.25rem;
        line-height: 1.6;
      }}
      .reveal blockquote {{
        font-size: 1.35rem;
        border-left: 0.25rem solid #d03189;
        padding-left: 1rem;
      }}
      .reveal pre code {{
        font-size: 1.1rem;
        line-height: 1.5;
      }}
    </style>
  </head>
  <body>
    <div class=\"reveal\">
      <div class=\"slides\">
{sections}
      </div>
    </div>
    <script src=\"https://cdn.jsdelivr.net/npm/reveal.js@5/dist/reveal.js\"></script>
    <script src=\"https://cdn.jsdelivr.net/npm/reveal.js@5/plugin/highlight/highlight.js\"></script>
    <script>
      Reveal.initialize({{
        hash: true,
        slideNumber: true,
        plugins: [ RevealHighlight ]
      }});
    </script>
  </body>
</html>
"""
    return template


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
            # Treat as regular text if not within an explicit code block.
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
                    # Remove leading bullet markers if present.
                    text_to_add = text_to_add.lstrip('- ')
                add_text(text_to_add)

        close_slide()

    return slides


def main() -> None:
    root = Path(__file__).parent
    slides = parse_prtty_files(root)
    output = render_document(slides)
    (root / "slides.html").write_text(output, encoding="utf-8")


if __name__ == "__main__":
    main()
