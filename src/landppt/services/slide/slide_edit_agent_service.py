from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional

from bs4 import BeautifulSoup
from pydantic import BaseModel


AgentEditMode = Literal["slide", "element"]


class SlideEditAgentRequest(BaseModel):
    projectId: str
    slideIndex: int
    userRequest: str
    chatHistory: Optional[List[Dict[str, Any]]] = None
    mode: AgentEditMode = "slide"
    slideTitle: Optional[str] = None
    slideContent: Optional[str] = None
    slideOutline: Optional[Dict[str, Any]] = None
    projectInfo: Optional[Dict[str, Any]] = None
    selectedElementHtml: Optional[str] = None
    selectedElementId: Optional[str] = None
    slideScreenshot: Optional[str] = None
    elementScreenshot: Optional[str] = None
    images: Optional[List[Dict[str, Any]]] = None
    visionEnabled: bool = False
    maxIterations: Optional[int] = None


class SlideEditAgentApplyRequest(BaseModel):
    proposalId: str
    projectId: str
    slideIndex: int
    expectedBaseHash: str
    htmlContent: str
    slideData: Optional[Dict[str, Any]] = None


@dataclass
class SlideEditAction:
    thought: str
    action: str
    action_input: Dict[str, Any] = field(default_factory=dict)
    raw_response: str = ""


@dataclass
class SlideEditValidationResult:
    valid: bool
    errors: List[str]
    warnings: List[str]
    sanitized_html: str


@dataclass
class SlideEditProposal:
    proposal_id: str
    base_hash: str
    summary: str
    changed_slide_indices: List[int]
    html_content: str
    validation: SlideEditValidationResult
    tool_transcript: List[Dict[str, Any]]
    slide_data: Dict[str, Any]
    created_at: float

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "proposalId": self.proposal_id,
            "baseHash": self.base_hash,
            "summary": self.summary,
            "changedSlideIndices": self.changed_slide_indices,
            "htmlContent": self.html_content,
            "validation": {
                "valid": self.validation.valid,
                "errors": self.validation.errors,
                "warnings": self.validation.warnings,
            },
            "toolTranscript": self.tool_transcript,
            "slideData": self.slide_data,
            "createdAt": self.created_at,
        }


def compute_slide_html_hash(html: str) -> str:
    normalized = (html or "").strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def coerce_agent_max_iterations(raw_value: Any) -> int:
    try:
        if raw_value is not None:
            return max(2, min(12, int(raw_value)))
    except (TypeError, ValueError):
        pass
    return 6


def _extract_json_payload(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None

    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()

    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    object_match = re.search(r"\{[\s\S]*\}", cleaned)
    if object_match:
        try:
            parsed = json.loads(object_match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    return None


def parse_agent_action(text: str) -> SlideEditAction:
    payload = _extract_json_payload(text or "")
    if not payload:
        summary = (text or "").strip() or "Agent returned an empty response."
        return SlideEditAction(
            thought="Model response was not structured; treating it as final summary.",
            action="final",
            action_input={"summary": summary},
            raw_response=text or "",
        )

    action_input = payload.get("action_input") or payload.get("input") or {}
    if not isinstance(action_input, dict):
        action_input = {"value": action_input}

    action_name = str(payload.get("action") or payload.get("tool") or "final")
    return SlideEditAction(
        thought=str(payload.get("thought") or payload.get("reasoning") or "").strip(),
        action=action_name.strip().lower().replace("-", "_"),
        action_input=action_input,
        raw_response=text or "",
    )


def strip_agent_ids(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for node in soup.find_all(True):
        for attr in ("data-agent-id", "data-quick-ai-id"):
            if attr in node.attrs:
                del node.attrs[attr]
    return str(soup).strip()


def sanitize_slide_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")

    for script in soup.find_all("script"):
        script.decompose()

    for node in soup.find_all(True):
        for attr in list(getattr(node, "attrs", {}).keys()):
            attr_lower = (attr or "").lower()
            value = node.attrs.get(attr)
            value_text = " ".join(value) if isinstance(value, list) else str(value or "")
            value_lower = value_text.strip().lower()
            if attr_lower.startswith("on"):
                del node.attrs[attr]
                continue
            if "javascript:" in value_lower:
                del node.attrs[attr]
                continue
            if attr_lower == "data-agent-id":
                del node.attrs[attr]

    return str(soup).strip()


class _SlideHtmlStructureParser(HTMLParser):
    _VOID_ELEMENTS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: List[str] = []
        self.errors: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        tag_name = tag.lower()
        if tag_name not in self._VOID_ELEMENTS:
            self.stack.append(tag_name)

    def handle_startendtag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        return None

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name in self._VOID_ELEMENTS:
            return
        if not self.stack:
            self.errors.append("html is malformed")
            return
        if self.stack[-1] == tag_name:
            self.stack.pop()
            return
        self.errors.append("html is malformed")

    def close(self) -> None:
        super().close()
        if self.stack:
            self.errors.append("html is malformed")


def _find_html_structure_errors(html: str) -> List[str]:
    parser = _SlideHtmlStructureParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return ["html is malformed"]
    return list(dict.fromkeys(parser.errors))


def validate_slide_html(html: str) -> SlideEditValidationResult:
    errors: List[str] = []
    warnings: List[str] = []
    original = html or ""
    original_lower = original.lower()

    if not original.strip():
        errors.append("html content is required")
        return SlideEditValidationResult(False, errors, warnings, "")

    if "<script" in original_lower:
        errors.append("script tags are not allowed")

    original_soup = BeautifulSoup(original, "html.parser")
    if any(attr.lower().startswith("on") for tag in original_soup.find_all(True) for attr in tag.attrs):
        errors.append("inline event handlers are not allowed")

    if "javascript:" in original_lower:
        errors.append("javascript urls are not allowed")

    errors.extend(_find_html_structure_errors(original))

    sanitized = sanitize_slide_html(original)
    soup = BeautifulSoup(sanitized, "html.parser")
    if not soup.find(True):
        errors.append("html must contain at least one element")

    root_text = soup.get_text(" ", strip=True)
    has_media = bool(soup.find(["img", "svg", "canvas", "video", "picture"]))
    if not root_text and not has_media:
        warnings.append("slide has no visible text or media")

    return SlideEditValidationResult(
        valid=not errors,
        errors=list(dict.fromkeys(errors)),
        warnings=warnings,
        sanitized_html=sanitized,
    )


EventEmitter = Callable[[Dict[str, Any]], Awaitable[None]]
