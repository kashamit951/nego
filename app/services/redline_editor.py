from __future__ import annotations

from dataclasses import dataclass
import copy
import io
from pathlib import Path
import zipfile
from datetime import datetime, timezone
from difflib import SequenceMatcher
from xml.etree import ElementTree as ET


DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
DOCX_W_NS = DOCX_NS["w"]


@dataclass(slots=True)
class RedlineDecision:
    source_type: str
    source_index: int
    action: str
    source_position: int | None = None
    source_comment_id: str | None = None
    source_text: str | None = None
    source_context_text: str | None = None
    modified_text: str | None = None
    reply_comment: str | None = None


class DocxRedlineEditorService:
    def apply_decisions(self, *, file_name: str, file_bytes: bytes, decisions: list[RedlineDecision]) -> bytes:
        suffix = Path(file_name).suffix.lower()
        if suffix != ".docx":
            raise ValueError("In-file redline updates are currently supported only for .docx")

        if not decisions:
            raise ValueError("No redline decisions provided")

        try:
            source_zip = zipfile.ZipFile(io.BytesIO(file_bytes), "r")
        except Exception as exc:
            raise ValueError(f"Failed to read DOCX: {exc}") from exc

        with source_zip:
            if "word/document.xml" not in source_zip.namelist():
                raise ValueError("Invalid DOCX: missing word/document.xml")
            document_xml = source_zip.read("word/document.xml")
            comment_part_names = [
                name
                for name in source_zip.namelist()
                if name.startswith("word/comments") and name.endswith(".xml")
            ]
            comment_part_names.sort()

            try:
                root = ET.fromstring(document_xml)
            except Exception as exc:
                raise ValueError(f"Failed to parse DOCX XML: {exc}") from exc

            comments_parts: dict[str, ET.Element] = {}
            comments_root: ET.Element | None = None
            comments_part_name: str | None = None
            for part_name in comment_part_names:
                try:
                    parsed_part = ET.fromstring(source_zip.read(part_name))
                    comments_parts[part_name] = parsed_part
                    if comments_root is None:
                        comments_root = parsed_part
                        comments_part_name = part_name
                except Exception:
                    continue

            tracked_nodes = self._collect_tracked_nodes(root)
            pending_replies: list[tuple[ET.Element, str, list[str]]] = []
            all_paragraphs = root.findall(".//w:p", DOCX_NS)
            paragraph_spans = self._build_paragraph_spans(all_paragraphs)

            for decision in decisions:
                if decision.source_type not in {"redline", "comment"}:
                    continue
                normalized_action = (decision.action or "").strip().lower()
                if decision.source_type == "comment":
                    note = (decision.reply_comment or "").strip()
                    if not note:
                        continue
                    if comments_parts and (decision.source_comment_id or "").strip():
                        target_paragraph = self._find_paragraph_by_comment_id(
                            root=root,
                            comment_id=str(decision.source_comment_id),
                        )
                        if target_paragraph is not None:
                            pending_replies.append((target_paragraph, note, [str(decision.source_comment_id)]))
                            continue
                    reply_paragraph = self._resolve_reply_paragraph(
                        all_paragraphs=all_paragraphs,
                        paragraph_spans=paragraph_spans,
                        source_position=decision.source_position,
                        source_text=str(decision.source_text or ""),
                        source_context_text=str(decision.source_context_text or ""),
                        source_index=decision.source_index,
                    )
                    if reply_paragraph is None:
                        continue
                    comment_ids = self._collect_comment_ids(reply_paragraph)
                    pending_replies.append((reply_paragraph, note, comment_ids))
                    continue
                node = self._resolve_tracked_node(tracked_nodes=tracked_nodes, decision=decision)
                if normalized_action == "reply":
                    note = (decision.reply_comment or "").strip()
                    if not note:
                        continue
                    if comments_parts and (decision.source_comment_id or "").strip():
                        target_paragraph = self._find_paragraph_by_comment_id(
                            root=root,
                            comment_id=str(decision.source_comment_id),
                        )
                        if target_paragraph is not None:
                            pending_replies.append((target_paragraph, note, [str(decision.source_comment_id)]))
                            continue
                    reply_paragraph = self._resolve_reply_paragraph(
                        all_paragraphs=all_paragraphs,
                        paragraph_spans=paragraph_spans,
                        source_position=decision.source_position,
                        source_text=str(decision.source_text or ""),
                        source_context_text=str(decision.source_context_text or ""),
                    )
                    if reply_paragraph is None and node is not None:
                        parent_map = self._build_parent_map(root)
                        reply_paragraph = self._find_ancestor(node=node, parent_map=parent_map, local_name="p")
                    if reply_paragraph is None:
                        continue
                    comment_ids = self._collect_comment_ids(reply_paragraph) + (self._collect_comment_ids(node) if node is not None else [])
                    unique_comment_ids: list[str] = []
                    for cid in comment_ids:
                        if cid not in unique_comment_ids:
                            unique_comment_ids.append(cid)
                    pending_replies.append((reply_paragraph, note, unique_comment_ids))
                    continue

                if node is None:
                    # Non-tracked signals (for example comment_range) cannot be
                    # accept/modify/reject in-place, but reply comments should still work.
                    note = (decision.reply_comment or "").strip()
                    if note:
                        reply_paragraph = self._resolve_reply_paragraph(
                            all_paragraphs=all_paragraphs,
                            paragraph_spans=paragraph_spans,
                            source_position=decision.source_position,
                            source_text=str(decision.source_text or ""),
                            source_context_text=str(decision.source_context_text or ""),
                            source_index=decision.source_index,
                        )
                        if reply_paragraph is not None:
                            comment_ids = self._collect_comment_ids(reply_paragraph)
                            pending_replies.append((reply_paragraph, note, comment_ids))
                            continue
                    # Skip silently for non-trackable rows instead of failing the entire batch.
                    continue
                parent_map = self._build_parent_map(root)
                paragraph = self._find_ancestor(node=node, parent_map=parent_map, local_name="p")
                comment_ids = self._collect_comment_ids(node) + (self._collect_comment_ids(paragraph) if paragraph is not None else [])
                unique_comment_ids: list[str] = []
                for cid in comment_ids:
                    if cid not in unique_comment_ids:
                        unique_comment_ids.append(cid)
                self._apply_single_decision(
                    root=root,
                    parent_map=parent_map,
                    node=node,
                    action=decision.action,
                    modified_text=decision.modified_text,
                )
                if decision.reply_comment and paragraph is not None:
                    note = decision.reply_comment.strip()
                    if note:
                        pending_replies.append((paragraph, note, unique_comment_ids))

            if pending_replies:
                if comments_root is not None:
                    self._apply_replies_as_docx_comments(comments_root=comments_root, replies=pending_replies)
                # If comments.xml is absent/unparseable, skip writing replies to avoid
                # corrupting unrelated document text with misplaced fallback content.

            updated_document_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            output_buffer = io.BytesIO()
            with zipfile.ZipFile(output_buffer, "w", compression=zipfile.ZIP_DEFLATED) as out_zip:
                for item in source_zip.infolist():
                    if item.filename == "word/document.xml":
                        out_zip.writestr(item, updated_document_xml)
                    elif item.filename in comments_parts:
                        updated_comments_xml = ET.tostring(comments_parts[item.filename], encoding="utf-8", xml_declaration=True)
                        out_zip.writestr(item, updated_comments_xml)
                    else:
                        out_zip.writestr(item, source_zip.read(item.filename))
            return output_buffer.getvalue()

    def _collect_tracked_nodes(self, root: ET.Element) -> list[ET.Element]:
        nodes: list[ET.Element] = []
        # Preserve the exact parser order: paragraph traversal, insertions first,
        # then deletions within each paragraph.
        for paragraph in root.findall(".//w:p", DOCX_NS):
            for inserted in paragraph.findall(".//w:ins", DOCX_NS):
                nodes.append(inserted)
            for deleted in paragraph.findall(".//w:del", DOCX_NS):
                nodes.append(deleted)
        return nodes

    def _resolve_tracked_node(self, *, tracked_nodes: list[ET.Element], decision: RedlineDecision) -> ET.Element | None:
        if not tracked_nodes:
            return None
        idx = int(decision.source_index)
        indexed = tracked_nodes[idx] if 0 <= idx < len(tracked_nodes) else None
        source_text = self._normalize_text(decision.source_text or "")
        if indexed is not None and source_text:
            node_text = self._normalize_text(self._collect_text(indexed) or self._collect_deleted_text(indexed))
            if node_text and self._similarity(node_text, source_text) >= 0.75:
                return indexed
        if indexed is not None and not source_text:
            return indexed

        if source_text:
            best_node: ET.Element | None = None
            best_score = 0.0
            for node in tracked_nodes:
                node_text = self._normalize_text(self._collect_text(node) or self._collect_deleted_text(node))
                if not node_text:
                    continue
                score = self._similarity(node_text, source_text)
                if source_text in node_text or node_text in source_text:
                    score = max(score, 0.92)
                if score > best_score:
                    best_score = score
                    best_node = node
            if best_node is not None and best_score >= 0.45:
                return best_node
        if source_text:
            return None
        return indexed

    def _resolve_reply_paragraph(
        self,
        *,
        all_paragraphs: list[ET.Element],
        paragraph_spans: list[tuple[ET.Element, int, int]],
        source_position: int | None,
        source_text: str,
        source_context_text: str,
        source_index: int | None = None,
    ) -> ET.Element | None:
        target = self._normalize_text(source_context_text or source_text)
        if source_position is not None and paragraph_spans:
            # Primary anchor: parser-provided character position in raw_text.
            # Keep this strict to avoid attaching replies to unrelated clauses.
            containing: ET.Element | None = None
            best_by_pos: ET.Element | None = None
            best_pos_distance: int | None = None
            for paragraph, start, end in paragraph_spans:
                if start <= source_position <= end:
                    containing = paragraph
                    best_by_pos = paragraph
                    best_pos_distance = 0
                    continue
                distance = min(abs(source_position - start), abs(source_position - end))
                if best_pos_distance is None or distance < best_pos_distance:
                    best_pos_distance = distance
                    best_by_pos = paragraph
            if containing is not None:
                return containing
            if best_by_pos is not None and best_pos_distance is not None and best_pos_distance <= 200:
                return best_by_pos

        # Secondary path only when source_position is unavailable.
        if source_position is None and target:
            matches: list[tuple[ET.Element, float]] = []
            for paragraph in all_paragraphs:
                text = self._normalize_text(self._collect_text(paragraph))
                if not text:
                    continue
                score = self._similarity(text, target)
                if target in text or text in target:
                    score = max(score, 0.96)
                if score >= 0.9:
                    matches.append((paragraph, score))
            if len(matches) == 1:
                return matches[0][0]
            if len(matches) > 1:
                matches.sort(key=lambda item: item[1], reverse=True)
                top_score = matches[0][1]
                second_score = matches[1][1]
                if top_score >= 0.95 and (top_score - second_score) >= 0.05:
                    return matches[0][0]
                if source_index is not None:
                    idx = max(0, min(len(matches) - 1, int(source_index)))
                    return matches[idx][0]

        # Last fallback for comment_range-like rows: use stable source_index to
        # anchor to a paragraph span when position/text matching is unavailable.
        if source_position is None and source_index is not None and paragraph_spans:
            idx = max(0, min(len(paragraph_spans) - 1, int(source_index)))
            return paragraph_spans[idx][0]
        return None

    def _build_paragraph_spans(self, paragraphs: list[ET.Element]) -> list[tuple[ET.Element, int, int]]:
        spans: list[tuple[ET.Element, int, int]] = []
        cursor = 0
        for paragraph in paragraphs:
            text = self._collect_text(paragraph)
            clean = " ".join((text or "").split()).strip()
            if not clean:
                continue
            start = cursor
            end = start + len(clean)
            spans.append((paragraph, start, end))
            cursor = end + 2
        return spans

    def _apply_single_decision(
        self,
        *,
        root: ET.Element,
        parent_map: dict[ET.Element, ET.Element],
        node: ET.Element,
        action: str,
        modified_text: str | None,
    ) -> None:
        tag = self._local_name(node.tag)
        if tag not in {"ins", "del"}:
            return
        if node not in parent_map:
            return

        normalized_action = (action or "").strip().lower()
        if normalized_action not in {"accept", "modify", "reject", "reply"}:
            raise ValueError(f"Unsupported action: {action}")
        if normalized_action == "reply":
            return

        parent = parent_map[node]
        index = list(parent).index(node)

        if tag == "ins":
            if normalized_action == "reject":
                parent.remove(node)
                return
            if normalized_action == "accept":
                replacement = [copy.deepcopy(child) for child in list(node)]
                self._replace_node(parent, index, node, replacement)
                return
            replacement = [self._make_run(modified_text or self._collect_text(node))]
            self._replace_node(parent, index, node, replacement)
            return

        # tag == "del"
        if normalized_action == "accept":
            parent.remove(node)
            return
        if normalized_action == "reject":
            restored = self._collect_deleted_text(node)
            replacement = [self._make_run(restored)] if restored else []
            self._replace_node(parent, index, node, replacement)
            return

        replacement_text = (modified_text or self._collect_deleted_text(node) or "").strip()
        replacement = [self._make_run(replacement_text)] if replacement_text else []
        self._replace_node(parent, index, node, replacement)

    @staticmethod
    def _replace_node(parent: ET.Element, index: int, node: ET.Element, replacement_nodes: list[ET.Element]) -> None:
        parent.remove(node)
        for offset, replacement in enumerate(replacement_nodes):
            parent.insert(index + offset, replacement)

    @staticmethod
    def _build_parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
        return {child: parent for parent in root.iter() for child in list(parent)}

    @staticmethod
    def _find_ancestor(*, node: ET.Element, parent_map: dict[ET.Element, ET.Element], local_name: str) -> ET.Element | None:
        current = node
        while current in parent_map:
            current = parent_map[current]
            if DocxRedlineEditorService._local_name(current.tag) == local_name:
                return current
        return None

    def _apply_replies_as_docx_comments(
        self,
        *,
        comments_root: ET.Element,
        replies: list[tuple[ET.Element, str, list[str]]],
    ) -> None:
        next_id = self._next_comment_id(comments_root)
        for paragraph, text, parent_comment_ids in replies:
            # Always create a new comment node for replies so Word shows this as a
            # separate user comment, not inline content appended into an existing one.
            parent_id = self._first_matching_comment_id(comments_root, parent_comment_ids)
            comment_id = next_id
            next_id += 1
            comments_root.append(
                self._make_comment_node(
                    comment_id=comment_id,
                    text=text,
                    author="Nego User",
                    parent_comment_id=parent_id,
                )
            )
            self._attach_comment_reference(paragraph=paragraph, comment_id=comment_id)

    @staticmethod
    def _next_comment_id(comments_root: ET.Element) -> int:
        max_id = -1
        for comment in comments_root.findall(".//w:comment", DOCX_NS):
            raw = comment.attrib.get(f"{{{DOCX_W_NS}}}id")
            try:
                if raw is not None:
                    max_id = max(max_id, int(str(raw)))
            except Exception:
                continue
        return max_id + 1

    @staticmethod
    def _make_comment_node(
        *,
        comment_id: int,
        text: str,
        author: str = "Nego App",
        parent_comment_id: str | None = None,
    ) -> ET.Element:
        comment = ET.Element(f"{{{DOCX_W_NS}}}comment")
        comment.set(f"{{{DOCX_W_NS}}}id", str(comment_id))
        comment.set(f"{{{DOCX_W_NS}}}author", author)
        comment.set(f"{{{DOCX_W_NS}}}date", datetime.now(timezone.utc).replace(microsecond=0).isoformat())

        paragraph = ET.SubElement(comment, f"{{{DOCX_W_NS}}}p")
        run = ET.SubElement(paragraph, f"{{{DOCX_W_NS}}}r")
        t = ET.SubElement(run, f"{{{DOCX_W_NS}}}t")
        t.text = text
        return comment

    @staticmethod
    def _attach_comment_reference(*, paragraph: ET.Element, comment_id: int) -> None:
        start = ET.Element(f"{{{DOCX_W_NS}}}commentRangeStart")
        start.set(f"{{{DOCX_W_NS}}}id", str(comment_id))
        paragraph.append(start)

        end = ET.Element(f"{{{DOCX_W_NS}}}commentRangeEnd")
        end.set(f"{{{DOCX_W_NS}}}id", str(comment_id))
        paragraph.append(end)

        run = ET.Element(f"{{{DOCX_W_NS}}}r")
        ref = ET.SubElement(run, f"{{{DOCX_W_NS}}}commentReference")
        ref.set(f"{{{DOCX_W_NS}}}id", str(comment_id))
        paragraph.append(run)

    @staticmethod
    def _collect_comment_ids(element: ET.Element | None) -> list[str]:
        if element is None:
            return []
        ids: list[str] = []
        for node in element.iter():
            local = str(node.tag or "").split("}")[-1].lower()
            if local not in {"commentrangestart", "commentreference"}:
                continue
            for key, value in node.attrib.items():
                if str(key).split("}")[-1].lower() == "id" and value is not None:
                    ids.append(str(value))
                    break
        return ids

    @staticmethod
    def _find_comment_node(comments_root: ET.Element, candidate_ids: list[str]) -> ET.Element | None:
        wanted = {str(cid).strip() for cid in candidate_ids if str(cid).strip()}
        if not wanted:
            return None
        for comment in comments_root.findall(".//w:comment", DOCX_NS):
            raw = comment.attrib.get(f"{{{DOCX_W_NS}}}id")
            if raw is not None and str(raw).strip() in wanted:
                return comment
        return None

    @staticmethod
    def _find_comment_node_across_parts(
        *,
        comments_parts: dict[str, ET.Element],
        candidate_ids: list[str],
    ) -> tuple[ET.Element | None, ET.Element | None]:
        wanted = {str(cid).strip() for cid in candidate_ids if str(cid).strip()}
        if not wanted:
            return None, None
        for _part_name, comments_root in comments_parts.items():
            for comment in comments_root.findall(".//w:comment", DOCX_NS):
                raw = comment.attrib.get(f"{{{DOCX_W_NS}}}id")
                if raw is not None and str(raw).strip() in wanted:
                    return comments_root, comment
        return None, None

    @staticmethod
    def _first_matching_comment_id(comments_root: ET.Element, candidate_ids: list[str]) -> str | None:
        wanted = {str(cid).strip() for cid in candidate_ids if str(cid).strip()}
        if not wanted:
            return None
        for comment in comments_root.findall(".//w:comment", DOCX_NS):
            raw = comment.attrib.get(f"{{{DOCX_W_NS}}}id")
            if raw is not None:
                clean = str(raw).strip()
                if clean in wanted:
                    return clean
        return None

    @staticmethod
    def _find_paragraph_by_comment_id(*, root: ET.Element, comment_id: str) -> ET.Element | None:
        wanted = str(comment_id or "").strip()
        if not wanted:
            return None
        for paragraph in root.findall(".//w:p", DOCX_NS):
            for node in paragraph.iter():
                local = str(node.tag or "").split("}")[-1].lower()
                if local not in {"commentrangestart", "commentreference"}:
                    continue
                for key, value in node.attrib.items():
                    if str(key).split("}")[-1].lower() == "id" and value is not None and str(value).strip() == wanted:
                        return paragraph
        return None

    @staticmethod
    def _local_name(tag: str) -> str:
        if "}" in tag:
            return tag.split("}", 1)[1]
        return tag

    @staticmethod
    def _collect_text(element: ET.Element) -> str:
        parts: list[str] = []
        for text_node in element.findall(".//w:t", DOCX_NS):
            if text_node.text:
                parts.append(text_node.text)
        return "".join(parts).strip()

    @staticmethod
    def _collect_deleted_text(element: ET.Element) -> str:
        parts: list[str] = []
        for text_node in element.findall(".//w:delText", DOCX_NS):
            if text_node.text:
                parts.append(text_node.text)
        if parts:
            return "".join(parts).strip()
        return DocxRedlineEditorService._collect_text(element)

    @staticmethod
    def _make_run(text: str) -> ET.Element:
        run = ET.Element(f"{{{DOCX_W_NS}}}r")
        text_node = ET.SubElement(run, f"{{{DOCX_W_NS}}}t")
        if text and (text.startswith(" ") or text.endswith(" ")):
            text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        text_node.text = text
        return run

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join((text or "").split()).strip().lower()

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        return float(SequenceMatcher(None, a, b).ratio())
