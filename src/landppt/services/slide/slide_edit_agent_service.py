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


def _attribute_value_text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value or "")


def _has_javascript_attribute_value(soup: BeautifulSoup) -> bool:
    for node in soup.find_all(True):
        for value in getattr(node, "attrs", {}).values():
            if "javascript:" in _attribute_value_text(value).strip().lower():
                return True
    return False


def sanitize_slide_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")

    for script in soup.find_all("script"):
        script.decompose()

    for node in soup.find_all(True):
        for attr in list(getattr(node, "attrs", {}).keys()):
            attr_lower = (attr or "").lower()
            value = node.attrs.get(attr)
            value_lower = _attribute_value_text(value).strip().lower()
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

    if "javascript:" in original_lower or _has_javascript_attribute_value(original_soup):
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


@dataclass
class SlideEditAgentContext:
    request: SlideEditAgentRequest
    project_id: str
    slide_index: int
    mode: AgentEditMode
    base_html: str
    base_hash: str
    slide_data: Dict[str, Any]
    project_info: Dict[str, Any]
    slide_outline: Dict[str, Any]
    selected_element_id: Optional[str] = None
    selected_element_html: Optional[str] = None

    @classmethod
    def from_request(cls, request: SlideEditAgentRequest) -> "SlideEditAgentContext":
        base_html = request.slideContent or ""
        slide_data = {
            "page_number": request.slideIndex,
            "title": request.slideTitle
            or (request.slideOutline or {}).get("title")
            or f"Slide {request.slideIndex}",
            "html_content": base_html,
            "slide_type": (request.slideOutline or {}).get("slide_type")
            or (request.slideOutline or {}).get("type")
            or "content",
            "content_points": (request.slideOutline or {}).get("content_points") or [],
            "metadata": {},
            "is_user_edited": True,
        }
        return cls(
            request=request,
            project_id=request.projectId,
            slide_index=request.slideIndex,
            mode=request.mode,
            base_html=base_html,
            base_hash=compute_slide_html_hash(base_html),
            slide_data=slide_data,
            project_info=request.projectInfo or {},
            slide_outline=request.slideOutline or {},
            selected_element_id=request.selectedElementId,
            selected_element_html=request.selectedElementHtml,
        )


class SlideEditToolRunner:
    _STYLE_WHITELIST = {
        "background",
        "background-color",
        "border",
        "border-radius",
        "box-shadow",
        "color",
        "display",
        "font-family",
        "font-size",
        "font-weight",
        "height",
        "left",
        "line-height",
        "margin",
        "margin-bottom",
        "margin-left",
        "margin-right",
        "margin-top",
        "max-height",
        "max-width",
        "min-height",
        "min-width",
        "opacity",
        "padding",
        "padding-bottom",
        "padding-left",
        "padding-right",
        "padding-top",
        "text-align",
        "top",
        "transform",
        "width",
        "z-index",
    }

    def __init__(self, context: SlideEditAgentContext):
        self.context = context
        self.current_html = context.base_html
        self.transcript: List[Dict[str, Any]] = []

    def available_tool_names(self) -> List[str]:
        return [
            "get_project_context",
            "get_slide",
            "list_slides",
            "inspect_slide_html",
            "select_elements",
            "replace_slide_html",
            "replace_element_html",
            "update_text",
            "update_style",
            "insert_element",
            "delete_element",
            "validate_slide_html",
            "preview_patch",
        ]

    async def execute_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        normalized = (tool_name or "").strip().lower().replace("-", "_")
        data = tool_input if isinstance(tool_input, dict) else {"value": tool_input}

        handlers = {
            "get_project_context": self._tool_get_project_context,
            "get_slide": self._tool_get_slide,
            "list_slides": self._tool_list_slides,
            "inspect_slide_html": self._tool_inspect_slide_html,
            "select_elements": self._tool_select_elements,
            "replace_slide_html": self._tool_replace_slide_html,
            "replace_element_html": self._tool_replace_element_html,
            "update_text": self._tool_update_text,
            "update_style": self._tool_update_style,
            "insert_element": self._tool_insert_element,
            "delete_element": self._tool_delete_element,
            "validate_slide_html": self._tool_validate_slide_html,
            "preview_patch": self._tool_preview_patch,
        }
        handler = handlers.get(normalized)
        if not handler:
            return {
                "success": False,
                "tool": normalized,
                "error": f"Unsupported slide edit tool: {normalized}",
                "available_tools": self.available_tool_names(),
            }

        result = handler(data)
        self.transcript.append(
            {
                "tool": normalized,
                "input": data,
                "success": bool(result.get("success")),
                "summary": result.get("summary") or result.get("error") or "",
            }
        )
        return result

    def _soup(self) -> BeautifulSoup:
        return BeautifulSoup(self.current_html or "", "html.parser")

    def _set_html_from_soup(self, soup: BeautifulSoup) -> None:
        self.current_html = str(soup).strip()

    def _tool_get_project_context(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": True,
            "tool": "get_project_context",
            "project": self.context.project_info,
            "slide_index": self.context.slide_index,
            "mode": self.context.mode,
            "outline": self.context.slide_outline,
            "summary": "Loaded project and outline context.",
        }

    def _tool_get_slide(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": True,
            "tool": "get_slide",
            "slide": {**self.context.slide_data, "html_content": self.current_html},
            "base_hash": self.context.base_hash,
            "summary": f"Loaded slide {self.context.slide_index}.",
        }

    def _tool_list_slides(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": True,
            "tool": "list_slides",
            "slides": [
                {
                    "slide_index": self.context.slide_index,
                    "title": self.context.slide_data.get("title"),
                    "slide_type": self.context.slide_data.get("slide_type"),
                }
            ],
            "summary": "Listed available slide summaries.",
        }

    def _tool_inspect_slide_html(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        soup = self._soup()
        headings = [
            {"selector": tag.name, "text": tag.get_text(" ", strip=True)}
            for tag in soup.find_all(["h1", "h2", "h3"])[:10]
        ]
        text_blocks = [
            {"selector": tag.name, "text": tag.get_text(" ", strip=True)[:300]}
            for tag in soup.find_all(["p", "li", "span", "div"])[:20]
            if tag.get_text(" ", strip=True)
        ]
        images = [
            {"src": img.get("src", ""), "alt": img.get("alt", "")}
            for img in soup.find_all("img")[:20]
        ]
        return {
            "success": True,
            "tool": "inspect_slide_html",
            "headings": headings,
            "text_blocks": text_blocks,
            "images": images,
            "summary": f"Found {len(headings)} headings, {len(text_blocks)} text blocks, and {len(images)} images.",
        }

    def _tool_select_elements(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        selector = str(tool_input.get("selector") or "").strip()
        text = str(tool_input.get("text") or "").strip().lower()
        soup = self._soup()
        matches = []
        candidates = soup.select(selector) if selector else soup.find_all(True)
        for idx, node in enumerate(candidates[:100], start=1):
            node_text = node.get_text(" ", strip=True)
            if text and text not in node_text.lower():
                continue
            agent_id = node.get("data-agent-id") or f"agent-el-{idx}"
            node["data-agent-id"] = agent_id
            matches.append({"agent_id": agent_id, "tag": node.name, "text": node_text[:200]})
        self._set_html_from_soup(soup)
        return {
            "success": True,
            "tool": "select_elements",
            "matches": matches,
            "summary": f"Selected {len(matches)} elements.",
        }

    def _resolve_one(self, soup: BeautifulSoup, tool_input: Dict[str, Any]):
        selector = str(tool_input.get("selector") or "").strip()
        element_id = str(
            tool_input.get("element_id") or self.context.selected_element_id or ""
        ).strip()
        if element_id:
            found = soup.select_one(f'[data-agent-id="{element_id}"]') or soup.select_one(
                f'[data-quick-ai-id="{element_id}"]'
            )
            if found:
                return found
        if selector:
            return soup.select_one(selector)
        return soup.find(True)

    def _tool_replace_slide_html(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        html = str(tool_input.get("html") or tool_input.get("value") or "").strip()
        validation = validate_slide_html(html)
        if not validation.sanitized_html:
            return {
                "success": False,
                "tool": "replace_slide_html",
                "error": "replacement html is empty",
            }
        self.current_html = validation.sanitized_html
        return {
            "success": validation.valid,
            "tool": "replace_slide_html",
            "errors": validation.errors,
            "summary": "Replaced full slide draft HTML.",
        }

    def _tool_replace_element_html(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        soup = self._soup()
        target = self._resolve_one(soup, tool_input)
        if not target:
            return {
                "success": False,
                "tool": "replace_element_html",
                "error": "target element not found",
            }
        fragment = BeautifulSoup(str(tool_input.get("html") or ""), "html.parser")
        replacement = fragment.find(True)
        if not replacement:
            return {
                "success": False,
                "tool": "replace_element_html",
                "error": "replacement element html is empty",
            }
        element_id = str(
            tool_input.get("element_id") or self.context.selected_element_id or ""
        ).strip()
        if element_id:
            replacement["data-quick-ai-id"] = element_id
        target.replace_with(replacement)
        self._set_html_from_soup(soup)
        return {
            "success": True,
            "tool": "replace_element_html",
            "summary": "Replaced selected element draft HTML.",
        }

    def _tool_update_text(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        soup = self._soup()
        target = self._resolve_one(soup, tool_input)
        if not target:
            return {"success": False, "tool": "update_text", "error": "target element not found"}
        target.clear()
        target.append(str(tool_input.get("text") or ""))
        self._set_html_from_soup(soup)
        return {"success": True, "tool": "update_text", "summary": "Updated element text."}

    def _tool_update_style(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        soup = self._soup()
        target = self._resolve_one(soup, tool_input)
        if not target:
            return {
                "success": False,
                "tool": "update_style",
                "error": "target element not found",
            }
        styles = tool_input.get("styles") if isinstance(tool_input.get("styles"), dict) else {}
        current_style = target.get("style", "")
        style_map: Dict[str, str] = {}
        for item in current_style.split(";"):
            if ":" in item:
                key, value = item.split(":", 1)
                style_map[key.strip().lower()] = value.strip()
        for key, value in styles.items():
            css_key = str(key).strip().lower()
            css_value = str(value).strip()
            if css_key in self._STYLE_WHITELIST and css_value and "url(" not in css_value.lower():
                style_map[css_key] = css_value
        target["style"] = "; ".join(f"{key}: {value}" for key, value in style_map.items())
        self._set_html_from_soup(soup)
        return {
            "success": True,
            "tool": "update_style",
            "summary": "Updated whitelisted element styles.",
        }

    def _tool_insert_element(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        soup = self._soup()
        parent = self._resolve_one(soup, {"selector": tool_input.get("parent_selector") or "body"})
        fragment = BeautifulSoup(str(tool_input.get("html") or ""), "html.parser")
        node = fragment.find(True)
        if not parent or not node:
            return {
                "success": False,
                "tool": "insert_element",
                "error": "parent or inserted element not found",
            }
        parent.append(node)
        self._set_html_from_soup(soup)
        return {"success": True, "tool": "insert_element", "summary": "Inserted element into draft."}

    def _tool_delete_element(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        soup = self._soup()
        target = self._resolve_one(soup, tool_input)
        if not target:
            return {"success": False, "tool": "delete_element", "error": "target element not found"}
        target.decompose()
        self._set_html_from_soup(soup)
        return {"success": True, "tool": "delete_element", "summary": "Deleted element from draft."}

    def _tool_validate_slide_html(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        validation = validate_slide_html(self.current_html)
        return {
            "success": validation.valid,
            "tool": "validate_slide_html",
            "errors": validation.errors,
            "warnings": validation.warnings,
            "summary": "Validated draft HTML.",
        }

    def _tool_preview_patch(self, tool_input: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": True,
            "tool": "preview_patch",
            "base_hash": self.context.base_hash,
            "new_hash": compute_slide_html_hash(self.current_html),
            "changed": compute_slide_html_hash(self.current_html) != self.context.base_hash,
            "summary": "Prepared before/after patch preview.",
        }

    def build_proposal(
        self, summary: str, changed_slide_indices: Optional[List[int]] = None
    ) -> SlideEditProposal:
        cleaned_html = strip_agent_ids(self.current_html)
        validation = validate_slide_html(cleaned_html)
        slide_data = {
            **self.context.slide_data,
            "html_content": validation.sanitized_html,
            "is_user_edited": True,
        }
        return SlideEditProposal(
            proposal_id=f"slide-edit-{uuid.uuid4().hex}",
            base_hash=self.context.base_hash,
            summary=summary or "Prepared slide edit proposal.",
            changed_slide_indices=changed_slide_indices or [self.context.slide_index],
            html_content=validation.sanitized_html,
            validation=validation,
            tool_transcript=list(self.transcript),
            slide_data=slide_data,
            created_at=time.time(),
        )


EventEmitter = Callable[[Dict[str, Any]], Awaitable[None]]
