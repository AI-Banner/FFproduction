"""FF Production 정적 사이트의 기본 구조와 내부 참조를 검증한다."""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
HTML_FILES = (ROOT / "index.html", ROOT / "portfolio.html")
REQUIRED_FILES = (ROOT / "robots.txt", ROOT / "sitemap.xml", ROOT / "llms.txt")


class SiteParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.refs: list[str] = []
        self.titles: list[str] = []
        self.h1_count = 0
        self.meta_description = False
        self.canonical = False
        self._in_title = False
        self._in_json_ld = False
        self._json_buffer: list[str] = []
        self.json_ld: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(values["id"] or "")
        if tag in {"a", "link"} and values.get("href"):
            self.refs.append(values["href"] or "")
        if tag in {"img", "script", "source", "iframe"} and values.get("src"):
            self.refs.append(values["src"] or "")
        if tag == "meta" and values.get("name", "").lower() == "description":
            self.meta_description = bool(values.get("content", "").strip())
        if tag == "link" and values.get("rel", "").lower() == "canonical":
            self.canonical = bool(values.get("href", "").strip())
        if tag == "title":
            self._in_title = True
        if tag == "h1":
            self.h1_count += 1
        if tag == "script" and values.get("type", "").lower() == "application/ld+json":
            self._in_json_ld = True
            self._json_buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag == "script" and self._in_json_ld:
            self.json_ld.append("".join(self._json_buffer).strip())
            self._in_json_ld = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.titles.append(data.strip())
        if self._in_json_ld:
            self._json_buffer.append(data)


def local_target(source: Path, ref: str) -> Path | None:
    parsed = urlsplit(ref)
    if parsed.scheme or parsed.netloc or ref.startswith(("#", "mailto:", "tel:", "data:")):
        return None
    path = unquote(parsed.path)
    if not path:
        return None
    if path == "/":
        return ROOT / "index.html"
    if path.startswith("/"):
        return ROOT / path.lstrip("/")
    return (source.parent / path).resolve()


def main() -> int:
    errors: list[str] = []

    for required in REQUIRED_FILES:
        if not required.is_file():
            errors.append(f"필수 파일 없음: {required.relative_to(ROOT)}")

    for html_file in HTML_FILES:
        if not html_file.is_file():
            errors.append(f"HTML 파일 없음: {html_file.name}")
            continue

        parser = SiteParser()
        parser.feed(html_file.read_text(encoding="utf-8"))
        label = html_file.name

        if not any(parser.titles):
            errors.append(f"{label}: title 없음")
        if parser.h1_count != 1:
            errors.append(f"{label}: h1은 1개여야 함 (현재 {parser.h1_count}개)")
        if not parser.meta_description:
            errors.append(f"{label}: meta description 없음")
        if not parser.canonical:
            errors.append(f"{label}: canonical 없음")

        duplicate_ids = sorted({item for item in parser.ids if parser.ids.count(item) > 1})
        if duplicate_ids:
            errors.append(f"{label}: 중복 id {', '.join(duplicate_ids)}")

        for block_number, raw_json in enumerate(parser.json_ld, start=1):
            try:
                json.loads(raw_json)
            except json.JSONDecodeError as exc:
                errors.append(f"{label}: JSON-LD #{block_number} 오류 ({exc})")

        for ref in parser.refs:
            target = local_target(html_file, ref)
            if target is not None and not target.exists():
                errors.append(f"{label}: 내부 파일 없음 {ref}")

    try:
        ET.parse(ROOT / "sitemap.xml")
    except (ET.ParseError, OSError) as exc:
        errors.append(f"sitemap.xml 오류: {exc}")

    if errors:
        print("사이트 검증 실패")
        for error in errors:
            print(f"- {error}")
        return 1

    print("사이트 검증 통과: HTML 메타데이터, JSON-LD, 내부 참조, 사이트맵 정상")
    return 0


if __name__ == "__main__":
    sys.exit(main())
