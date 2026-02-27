from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree as ET


DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


@dataclass(slots=True)
class ParsedCorpusDocument:
    raw_text: str
    redline_events: list[dict] = field(default_factory=list)
    comments: list[dict] = field(default_factory=list)
    parser_status: str = "ready"
    parse_error: str | None = None


class CorpusParserService:
    SUPPORTED_EXTENSIONS = {".txt", ".md", ".docx", ".pdf", ".rtf"}

    def parse(self, file_path: Path) -> ParsedCorpusDocument:
        suffix = file_path.suffix.lower()
        if suffix not in self.SUPPORTED_EXTENSIONS:
            return ParsedCorpusDocument(
                raw_text="",
                parser_status="unsupported",
                parse_error=f"Unsupported file extension: {suffix}",
            )

        if suffix in {".txt", ".md", ".rtf"}:
            return self._parse_plain_text(file_path)
        if suffix == ".docx":
            return self._parse_docx(file_path)
        if suffix == ".pdf":
            return self._parse_pdf(file_path)

        return ParsedCorpusDocument(
            raw_text="",
            parser_status="unsupported",
            parse_error=f"Unsupported file extension: {suffix}",
        )

    def _parse_plain_text(self, file_path: Path) -> ParsedCorpusDocument:
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            return ParsedCorpusDocument(
                raw_text="",
                parser_status="error",
                parse_error=f"Failed to read text file: {exc}",
            )

        redlines: list[dict] = []
        comments: list[dict] = []

        for match in re.finditer(r"\[\[ADD:(.*?)\]\]", text, flags=re.IGNORECASE | re.DOTALL):
            redlines.append({"type": "insertion", "text": match.group(1).strip(), "source": "markup"})
        for match in re.finditer(r"\[\[DEL:(.*?)\]\]", text, flags=re.IGNORECASE | re.DOTALL):
            redlines.append({"type": "deletion", "text": match.group(1).strip(), "source": "markup"})

        for line in text.splitlines():
            lowered = line.lower().strip()
            if lowered.startswith("comment:"):
                comments.append({"text": line.split(":", 1)[1].strip(), "source": "inline"})

        self._annotate_event_positions(text, redlines)
        self._annotate_event_positions(text, comments, text_key="text")
        return ParsedCorpusDocument(raw_text=text, redline_events=redlines, comments=comments)

    def _parse_docx(self, file_path: Path) -> ParsedCorpusDocument:
        try:
            with zipfile.ZipFile(file_path, "r") as archive:
                document_xml = archive.read("word/document.xml")
                comment_part_names = [
                    name
                    for name in archive.namelist()
                    if re.fullmatch(r"word/comments(?:\d+)?\.xml", name)
                ]
                comment_part_names.sort()
                comments_xml_parts = [archive.read(name) for name in comment_part_names]
                people_xml = archive.read("word/people.xml") if "word/people.xml" in archive.namelist() else None
        except Exception as exc:
            return ParsedCorpusDocument(
                raw_text="",
                parser_status="error",
                parse_error=f"Failed to open DOCX: {exc}",
            )

        try:
            root = ET.fromstring(document_xml)
        except Exception as exc:
            return ParsedCorpusDocument(
                raw_text="",
                parser_status="error",
                parse_error=f"Failed to parse DOCX XML: {exc}",
            )

        active_comment_ids_by_element = self._collect_active_comment_ids_by_element(root)
        comment_range_text_by_id = self._collect_comment_range_texts(root)

        paragraph_rows: list[dict] = []
        for paragraph in root.findall(".//w:p", DOCX_NS):
            text = self._collect_text(paragraph)
            text = text.strip() if text else ""
            if not text:
                continue
            paragraph_rows.append(
                {
                    "text": text,
                    "comment_ids": self._collect_comment_ids(paragraph),
                }
            )
        raw_text = "\n\n".join(row["text"] for row in paragraph_rows).strip()

        comment_anchor_by_id: dict[str, dict] = {}
        cursor = 0
        for row in paragraph_rows:
            para_text = str(row.get("text") or "")
            start = cursor
            anchor_preview = para_text[:300]
            for cid in row.get("comment_ids") or []:
                if cid not in comment_anchor_by_id:
                    comment_anchor_by_id[cid] = {
                        "anchor_text": anchor_preview,
                        "position": start,
                    }
            cursor = start + len(para_text) + 2

        comments: list[dict] = []
        comments_by_id: dict[str, str] = {}
        people_by_id: dict[str, str] = self._parse_people_xml(people_xml) if people_xml else {}
        if comments_xml_parts:
            try:
                for comments_xml in comments_xml_parts:
                    comments_root = ET.fromstring(comments_xml)
                    for comment in comments_root.findall(".//w:comment", DOCX_NS):
                        comment_id = comment.attrib.get(f"{{{DOCX_NS['w']}}}id")
                        comment_text = self._collect_text(comment)
                        author = self._extract_comment_author(comment, people_by_id)
                        if comment_id is not None and comment_text and not comments_by_id.get(str(comment_id)):
                            comments_by_id[str(comment_id)] = comment_text
                        comments.append(
                            {
                                "id": comment_id,
                                "author": author or None,
                                "timestamp": comment.attrib.get(f"{{{DOCX_NS['w']}}}date"),
                                "text": comment_text,
                                "source": "comments",
                                "anchor_text": (
                                    comment_anchor_by_id.get(str(comment_id), {}).get("anchor_text")
                                    if comment_id is not None
                                    else None
                                ),
                                "position": (
                                    comment_anchor_by_id.get(str(comment_id), {}).get("position")
                                    if comment_id is not None
                                    else None
                                ),
                            }
                        )
            except Exception:
                comments.append(
                    {
                        "text": "comments part exists but could not be parsed",
                        "source": "comments",
                    }
                )

        # Some DOCX variants expose comment anchors in document.xml but not readable
        # comment bodies in comments*.xml. Preserve those anchors as synthetic comments.
        existing_comment_ids = {
            str(row.get("id")).strip()
            for row in comments
            if row.get("id") is not None and str(row.get("id")).strip()
        }
        for cid, anchor in comment_anchor_by_id.items():
            clean_cid = str(cid).strip()
            if not clean_cid:
                continue
            if not comments_by_id.get(clean_cid):
                comments_by_id[clean_cid] = f"Comment attached in document (id: {clean_cid})"
            if clean_cid in existing_comment_ids:
                continue
            comments.append(
                {
                    "id": clean_cid,
                    "author": None,
                    "timestamp": None,
                    "text": comments_by_id[clean_cid],
                    "source": "comments_anchor",
                    "anchor_text": anchor.get("anchor_text"),
                    "position": anchor.get("position"),
                }
            )

        redline_events: list[dict] = []
        for paragraph in root.findall(".//w:p", DOCX_NS):
            paragraph_text = self._collect_text(paragraph)
            paragraph_comment_ids = self._collect_comment_ids(paragraph)

            for inserted in paragraph.findall(".//w:ins", DOCX_NS):
                text = self._collect_text(inserted)
                if not text:
                    continue
                inherited_comment_ids = active_comment_ids_by_element.get(id(inserted), [])
                raw_ids = paragraph_comment_ids + inherited_comment_ids + self._collect_comment_ids(inserted)
                comment_ids: list[str] = []
                for cid in raw_ids:
                    if cid not in comment_ids:
                        comment_ids.append(cid)
                linked_comments = [comments_by_id[cid] for cid in comment_ids if cid in comments_by_id and comments_by_id[cid]]
                linked_comment_text = " ".join(linked_comments).strip() if linked_comments else None
                if not linked_comment_text and comment_ids:
                    linked_comment_text = f"Comment attached in document (id: {', '.join(comment_ids[:3])})"
                redline_events.append(
                    {
                        "type": "insertion",
                        "text": text,
                        "author": inserted.attrib.get(f"{{{DOCX_NS['w']}}}author"),
                        "timestamp": inserted.attrib.get(f"{{{DOCX_NS['w']}}}date"),
                        "source": "track_changes",
                        "comment_ids": comment_ids,
                        "comment_text": linked_comment_text,
                        "paragraph_text": paragraph_text,
                    }
                )

            for deleted in paragraph.findall(".//w:del", DOCX_NS):
                text = self._collect_deleted_text(deleted)
                if not text:
                    continue
                inherited_comment_ids = active_comment_ids_by_element.get(id(deleted), [])
                raw_ids = paragraph_comment_ids + inherited_comment_ids + self._collect_comment_ids(deleted)
                comment_ids: list[str] = []
                for cid in raw_ids:
                    if cid not in comment_ids:
                        comment_ids.append(cid)
                linked_comments = [comments_by_id[cid] for cid in comment_ids if cid in comments_by_id and comments_by_id[cid]]
                linked_comment_text = " ".join(linked_comments).strip() if linked_comments else None
                if not linked_comment_text and comment_ids:
                    linked_comment_text = f"Comment attached in document (id: {', '.join(comment_ids[:3])})"
                redline_events.append(
                    {
                        "type": "deletion",
                        "text": text,
                        "author": deleted.attrib.get(f"{{{DOCX_NS['w']}}}author"),
                        "timestamp": deleted.attrib.get(f"{{{DOCX_NS['w']}}}date"),
                        "source": "track_changes",
                        "comment_ids": comment_ids,
                        "comment_text": linked_comment_text,
                        "paragraph_text": paragraph_text,
                    }
                )

        # Fallback: when DOCX has comment-anchored ranges but no tracked insert/delete
        # nodes, synthesize redline events from the comment ranges so negotiation flow
        # can still show redline+comment pairs.
        if not redline_events and comment_range_text_by_id:
            for cid, range_text in comment_range_text_by_id.items():
                clean_text = " ".join(str(range_text or "").split()).strip()
                if not clean_text:
                    continue
                linked_comment_text = (
                    str(comments_by_id.get(cid) or "").strip()
                    or f"Comment attached in document (id: {cid})"
                )
                redline_events.append(
                    {
                        "type": "comment_range",
                        "text": clean_text,
                        "author": None,
                        "timestamp": None,
                        "source": "comment_range",
                        "comment_ids": [cid],
                        "comment_text": linked_comment_text,
                        "paragraph_text": clean_text,
                    }
                )

        if not comments:
            synthetic_ids: list[str] = []
            for event in redline_events:
                for cid in event.get("comment_ids") or []:
                    clean = str(cid).strip()
                    if clean and clean not in synthetic_ids:
                        synthetic_ids.append(clean)
            for cid in synthetic_ids:
                comments.append(
                    {
                        "id": cid,
                        "author": None,
                        "timestamp": None,
                        "text": f"Comment attached in document (id: {cid})",
                        "source": "comments_anchor_only",
                    }
                )

        self._annotate_event_positions(raw_text, redline_events)
        self._annotate_event_positions(raw_text, comments, text_key="text")
        return ParsedCorpusDocument(raw_text=raw_text, redline_events=redline_events, comments=comments)

    def _parse_pdf(self, file_path: Path) -> ParsedCorpusDocument:
        try:
            from pypdf import PdfReader
        except Exception:
            return ParsedCorpusDocument(
                raw_text="",
                parser_status="error",
                parse_error="pypdf dependency is missing; install pypdf to parse PDF corpus files",
            )

        try:
            reader = PdfReader(str(file_path))
        except Exception as exc:
            return ParsedCorpusDocument(
                raw_text="",
                parser_status="error",
                parse_error=f"Failed to open PDF: {exc}",
            )

        texts: list[str] = []
        comments: list[dict] = []

        for page_index, page in enumerate(reader.pages):
            try:
                page_text = page.extract_text() or ""
            except Exception:
                page_text = ""
            if page_text.strip():
                texts.append(page_text.strip())

            annots = page.get("/Annots")
            if annots:
                for annot_ref in annots:
                    try:
                        annot = annot_ref.get_object()
                        comments.append(
                            {
                                "page": page_index + 1,
                                "subtype": str(annot.get("/Subtype")),
                                "author": str(annot.get("/T")) if annot.get("/T") else None,
                                "text": str(annot.get("/Contents")) if annot.get("/Contents") else None,
                                "source": "pdf_annotation",
                            }
                        )
                    except Exception:
                        continue

        raw_text = "\n\n".join(texts).strip()
        return ParsedCorpusDocument(raw_text=raw_text, redline_events=[], comments=comments)

    @staticmethod
    def _collect_text(element: ET.Element) -> str:
        parts: list[str] = []
        for text_node in element.findall(".//w:t", DOCX_NS):
            if text_node.text:
                parts.append(text_node.text)
        return "".join(parts).strip()

    @staticmethod
    def _local_name(value: str) -> str:
        return str(value or "").split("}")[-1]

    @classmethod
    def _extract_attr_local(cls, element: ET.Element, local_name: str) -> str | None:
        target = local_name.lower()
        for key, value in element.attrib.items():
            if cls._local_name(str(key)).lower() == target and value is not None:
                clean = str(value).strip()
                if clean:
                    return clean
        return None

    @classmethod
    def _extract_comment_author(cls, comment: ET.Element, people_by_id: dict[str, str]) -> str:
        for key in ("author", "authorName", "userName", "displayName"):
            value = cls._extract_attr_local(comment, key)
            if value:
                return value
        initials = cls._extract_attr_local(comment, "initials")
        if initials:
            return initials
        for id_key in ("personId", "authorId", "userId", "id"):
            ref = cls._extract_attr_local(comment, id_key)
            if ref and people_by_id.get(ref):
                return people_by_id[ref]
        # Last-resort: look for any non-empty author-like attribute.
        for key, value in comment.attrib.items():
            local = cls._local_name(str(key)).lower()
            clean = str(value or "").strip()
            if not clean:
                continue
            if "author" in local or "user" in local or "name" in local:
                if people_by_id.get(clean):
                    return people_by_id[clean]
                return clean
        return ""

    @classmethod
    def _parse_people_xml(cls, people_xml: bytes) -> dict[str, str]:
        mapping: dict[str, str] = {}
        try:
            root = ET.fromstring(people_xml)
        except Exception:
            return mapping
        for person in root.iter():
            if cls._local_name(str(person.tag)).lower() != "person":
                continue
            author = ""
            for key in ("author", "name", "displayName", "userName", "authorName"):
                author = cls._extract_attr_local(person, key) or ""
                if author:
                    break
            if not author:
                for key, value in person.attrib.items():
                    local = cls._local_name(str(key)).lower()
                    clean = str(value or "").strip()
                    if clean and ("author" in local or "name" in local or "user" in local):
                        author = clean
                        break
            for id_key in ("personId", "authorId", "userId", "id"):
                person_id = cls._extract_attr_local(person, id_key)
                if person_id and author:
                    mapping[person_id] = author
        return mapping

    @staticmethod
    def _collect_deleted_text(element: ET.Element) -> str:
        parts: list[str] = []
        for text_node in element.findall(".//w:delText", DOCX_NS):
            if text_node.text:
                parts.append(text_node.text)
        if parts:
            return "".join(parts).strip()
        return CorpusParserService._collect_text(element)

    @staticmethod
    def _collect_comment_ids(element: ET.Element) -> list[str]:
        ids: list[str] = []
        for marker in element.iter():
            tag = str(marker.tag or "")
            local_tag = tag.split("}")[-1].lower()
            if local_tag not in {"commentrangestart", "commentreference"}:
                continue
            for key, value in marker.attrib.items():
                local_attr = str(key).split("}")[-1].lower()
                if local_attr == "id" and value is not None:
                    ids.append(str(value))
                    break
        unique_ids: list[str] = []
        for value in ids:
            if value not in unique_ids:
                unique_ids.append(value)
        return unique_ids

    @staticmethod
    def _collect_active_comment_ids_by_element(root: ET.Element) -> dict[int, list[str]]:
        mapping: dict[int, list[str]] = {}
        active: list[str] = []

        def _local(value: str) -> str:
            return str(value or "").split("}")[-1].lower()

        def _id_from_attrib(node: ET.Element) -> str | None:
            for key, value in node.attrib.items():
                if _local(key) == "id" and value is not None:
                    clean = str(value).strip()
                    if clean:
                        return clean
            return None

        def _walk(node: ET.Element) -> None:
            for child in list(node):
                local = _local(child.tag)
                if local == "commentrangestart":
                    marker_id = _id_from_attrib(child)
                    if marker_id and marker_id not in active:
                        active.append(marker_id)
                    continue
                if local == "commentrangeend":
                    marker_id = _id_from_attrib(child)
                    if marker_id and marker_id in active:
                        active.remove(marker_id)
                    continue
                if local in {"ins", "del"} and active:
                    mapping[id(child)] = list(active)
                _walk(child)

        _walk(root)
        return mapping

    @staticmethod
    def _collect_comment_range_texts(root: ET.Element) -> dict[str, str]:
        ranges: dict[str, list[str]] = {}
        active: list[str] = []

        def _local(value: str) -> str:
            return str(value or "").split("}")[-1].lower()

        def _id_from_attrib(node: ET.Element) -> str | None:
            for key, value in node.attrib.items():
                if _local(key) == "id" and value is not None:
                    clean = str(value).strip()
                    if clean:
                        return clean
            return None

        def _walk(node: ET.Element) -> None:
            for child in list(node):
                local = _local(child.tag)
                if local == "commentrangestart":
                    marker_id = _id_from_attrib(child)
                    if marker_id and marker_id not in active:
                        active.append(marker_id)
                    continue
                if local == "commentrangeend":
                    marker_id = _id_from_attrib(child)
                    if marker_id and marker_id in active:
                        active.remove(marker_id)
                    continue
                if local in {"t", "deltext"} and active:
                    text = str(child.text or "").strip()
                    if text:
                        for cid in active:
                            ranges.setdefault(cid, []).append(text)
                _walk(child)

        _walk(root)
        return {cid: " ".join(parts).strip() for cid, parts in ranges.items() if parts}

    @staticmethod
    def _annotate_event_positions(raw_text: str, events: list[dict], text_key: str = "text") -> None:
        if not raw_text or not events:
            return
        lowered = raw_text.lower()
        cursor = 0
        for event in events:
            if event.get("position") is not None:
                continue
            text = str(event.get(text_key) or "").strip()
            if not text:
                continue
            needle = text.lower()
            idx = lowered.find(needle, cursor)
            if idx < 0:
                idx = lowered.find(needle)
            if idx >= 0:
                event["position"] = idx
                cursor = idx + max(1, len(needle))
