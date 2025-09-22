"""Export .prtty slide decks to a basic PDF document.

This script performs a best-effort conversion of the custom ``.prtty``
presentation files in this repository into a single PDF.  The original
format supports a rich set of directives (animations, colours, precise
positioning, etc.).  The converter implemented here focuses on the text
content so that the resulting PDF contains the essential information even
though the visual formatting is simplified.

Usage::

    python export_to_pdf.py

The PDF is written to ``slides.pdf`` in the repository root.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable, List


class PrttyParser:
    """Parse ``.prtty`` files into a list of slide text blocks."""

    _IMAGE_PATTERN = re.compile(r"./images/([^\"]+)")

    def parse_paths(self, paths: Iterable[Path]) -> List[List[str]]:
        slides: List[List[str]] = []
        for path in paths:
            slides.extend(self.parse_text(path.read_text(encoding="utf-8")))
        return slides

    def parse_text(self, text: str) -> List[List[str]]:
        slides: List[List[str]] = []
        current: List[str] = []
        for raw_line in text.splitlines():
            stripped = raw_line.strip()

            if stripped.startswith(".slide"):
                if current:
                    slides.append(self._clean_slide(current))
                current = []
                continue

            if stripped.startswith(".prelude"):
                if current:
                    slides.append(self._clean_slide(current))
                current = []
                continue

            text_line = self._extract_text(raw_line)
            if text_line is None:
                continue

            if text_line == "":
                # Avoid piling up more than one blank separator in a row.
                if current and current[-1] == "":
                    continue
                current.append("")
                continue

            current.append(text_line)

        if current:
            slides.append(self._clean_slide(current))

        return slides

    def _extract_text(self, line: str) -> str | None:
        stripped = line.strip()

        if not stripped:
            return ""

        # Explicit control directives that never produce visible text.
        for prefix in (
            ".waypoint",
            ".wait",
            ".home",
            ".vcenter",
            ".center",
            ".style",
            ".list",
            ".quote",
            ".type",
            ".alternate",
            ".vspace",
            ".clear",
        ):
            if stripped.startswith(prefix) and "<<" not in stripped:
                return None

        if stripped.startswith(".nl"):
            return ""

        if stripped.startswith(".exec"):
            match = self._IMAGE_PATTERN.search(stripped)
            if match:
                return f"[image: {match.group(1)}]"
            return None

        if stripped.startswith(".moveTo") or stripped.startswith(".backspace"):
            if "<<" in stripped:
                text = stripped.split("<<", 1)[1]
            elif "<" in stripped:
                text = stripped.split("<", 1)[1]
            else:
                return None
            return self._normalise(text)

        if stripped.startswith(">"):
            return stripped.lstrip(">").strip()

        if "<<" in line:
            text = line.split("<<")[-1]
            return self._normalise(text)

        if stripped.startswith("."):
            if "<" in stripped:
                return self._normalise(stripped.split("<", 1)[1])
            return None

        return stripped

    def _normalise(self, text: str) -> str:
        text = text.strip()
        if "<" in text:
            text = text.split("<", 1)[0].strip()
        return text

    def _clean_slide(self, lines: List[str]) -> List[str]:
        """Remove leading/trailing blank lines from a slide."""

        start = 0
        end = len(lines)
        while start < end and lines[start] == "":
            start += 1
        while end > start and lines[end - 1] == "":
            end -= 1
        return lines[start:end]


def escape_pdf_text(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )


class SimplePDF:
    """Very small PDF writer that handles plain text pages."""

    def __init__(
        self,
        width: int = 612,
        height: int = 792,
        margin: int = 72,
        font_size: int = 18,
        line_height: int = 24,
    ) -> None:
        self.width = width
        self.height = height
        self.margin = margin
        self.font_size = font_size
        self.line_height = line_height

        self.objects: List[bytes | None] = [None]
        self.catalog_obj = self._reserve_object()
        self.pages_obj = self._reserve_object()
        self.font_obj = self._add_object(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n"
        )

        self.pages: List[tuple[int, int]] = []
        self._structures_finalised = False

    def _reserve_object(self) -> int:
        self.objects.append(None)
        return len(self.objects) - 1

    def _add_object(self, data: bytes) -> int:
        if not data.endswith(b"\n"):
            data += b"\n"
        self.objects.append(data)
        return len(self.objects) - 1

    def _set_object(self, index: int, data: bytes) -> None:
        if not data.endswith(b"\n"):
            data += b"\n"
        self.objects[index] = data

    def add_page(self, lines: Iterable[str]) -> None:
        body = self._build_stream(lines)
        length = len(body)
        content = b"<< /Length %d >>\nstream\n" % length + body + b"endstream\n"
        content_obj = self._add_object(content)
        page_obj = self._reserve_object()
        self.pages.append((page_obj, content_obj))
        self._structures_finalised = False

    def _build_stream(self, lines: Iterable[str]) -> bytes:
        parts = [
            b"BT",
            f"/F1 {self.font_size} Tf".encode("ascii"),
            f"{self.margin} {self.height - self.margin} Td".encode("ascii"),
        ]

        for line in lines:
            if line == "":
                parts.append(f"0 -{self.line_height} Td".encode("ascii"))
                continue

            parts.append(f"({escape_pdf_text(line)}) Tj".encode("utf-8"))
            parts.append(f"0 -{self.line_height} Td".encode("ascii"))

        parts.append(b"ET")
        return b"\n".join(parts) + b"\n"

    def _finalise_structures(self) -> None:
        if self._structures_finalised:
            return

        kids = []
        for page_obj, content_obj in self.pages:
            page_dict = (
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] "
                b"/Resources << /Font << /F1 %d 0 R >> >> "
                b"/Contents %d 0 R >>\n"
                % (
                    self.pages_obj,
                    self.width,
                    self.height,
                    self.font_obj,
                    content_obj,
                )
            )
            self._set_object(page_obj, page_dict)
            kids.append(f"{page_obj} 0 R".encode("ascii"))

        kids_list = b"[ " + b" ".join(kids) + b" ]" if kids else b"[ ]"
        pages_dict = (
            b"<< /Type /Pages /Count %d /Kids %s >>\n"
            % (len(self.pages), kids_list)
        )
        self._set_object(self.pages_obj, pages_dict)
        catalog_dict = b"<< /Type /Catalog /Pages %d 0 R >>\n" % self.pages_obj
        self._set_object(self.catalog_obj, catalog_dict)

        self._structures_finalised = True

    def save(self, path: Path) -> None:
        self._finalise_structures()

        if any(obj is None for obj in self.objects[1:]):
            raise RuntimeError("PDF objects were not fully initialised")

        result = bytearray()
        result.extend(b"%PDF-1.4\n")

        offsets = []
        for index, obj in enumerate(self.objects[1:], start=1):
            offsets.append(len(result))
            result.extend(f"{index} 0 obj\n".encode("ascii"))
            assert obj is not None
            result.extend(obj)
            if not obj.endswith(b"\n"):
                result.extend(b"\n")
            result.extend(b"endobj\n")

        xref_position = len(result)
        total_objects = len(self.objects) - 1
        result.extend(f"xref\n0 {total_objects + 1}\n".encode("ascii"))
        result.extend(b"0000000000 65535 f \n")
        for offset in offsets:
            result.extend(f"{offset:010} 00000 n \n".encode("ascii"))

        result.extend(b"trailer\n")
        result.extend(
            f"<< /Size {total_objects + 1} /Root {self.catalog_obj} 0 R >>\n".encode(
                "ascii"
            )
        )
        result.extend(b"startxref\n")
        result.extend(f"{xref_position}\n".encode("ascii"))
        result.extend(b"%%EOF\n")

        path.write_bytes(result)


def build_pdf(slides: Iterable[List[str]], destination: Path) -> None:
    pdf = SimplePDF()
    for slide in slides:
        pdf.add_page(slide)
    pdf.save(destination)


def main() -> None:
    parser = PrttyParser()
    prtty_files = sorted(Path.cwd().glob("*.prtty"))
    slides = parser.parse_paths(prtty_files)

    output_path = Path("slides.pdf")
    build_pdf(slides, output_path)
    print(f"Wrote {output_path} with {len(slides)} slides")


if __name__ == "__main__":
    main()
