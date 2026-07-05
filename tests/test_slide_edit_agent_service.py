import json

import pytest

from landppt.services.slide.slide_edit_agent_service import (
    SlideEditAgentContext,
    SlideEditAgentRequest,
    SlideEditToolRunner,
    compute_slide_html_hash,
    coerce_agent_max_iterations,
    parse_agent_action,
    sanitize_slide_html,
    strip_agent_ids,
    validate_slide_html,
)


def test_parse_agent_action_supports_json_code_fence():
    action = parse_agent_action(
        "```json\n"
        + json.dumps(
            {
                "thought": "Inspect the slide before editing.",
                "action": "inspect_slide_html",
                "action_input": {"slide_index": 1},
            }
        )
        + "\n```"
    )

    assert action.thought == "Inspect the slide before editing."
    assert action.action == "inspect_slide_html"
    assert action.action_input == {"slide_index": 1}


def test_parse_agent_action_falls_back_to_final_for_unparseable_text():
    action = parse_agent_action("I cannot parse this as JSON.")

    assert action.action == "final"
    assert action.action_input["summary"] == "I cannot parse this as JSON."


def test_coerce_agent_max_iterations_defaults_and_clamps():
    assert coerce_agent_max_iterations(None) == 6
    assert coerce_agent_max_iterations(1) == 2
    assert coerce_agent_max_iterations(8) == 8
    assert coerce_agent_max_iterations(99) == 12
    assert coerce_agent_max_iterations("bad") == 6


def test_compute_slide_html_hash_is_stable_for_equivalent_text():
    assert compute_slide_html_hash(" <div>A</div>\n") == compute_slide_html_hash("<div>A</div>")
    assert compute_slide_html_hash("<div>A</div>") != compute_slide_html_hash("<div>B</div>")


def test_sanitize_slide_html_removes_scripts_event_handlers_and_agent_ids():
    html = (
        '<div data-agent-id="a1" onclick="bad()" style="width:1280px;height:720px">'
        '<a href="javascript:bad()">x</a><script>alert(1)</script>'
        "</div>"
    )

    sanitized = sanitize_slide_html(html)

    assert "<script" not in sanitized.lower()
    assert "onclick" not in sanitized.lower()
    assert "javascript:" not in sanitized.lower()
    assert "data-agent-id" not in strip_agent_ids(sanitized)


def test_validate_slide_html_reports_unsafe_original_html():
    result = validate_slide_html('<div><script>alert(1)</script><p onclick="x()">Hi</p></div>')

    assert result.valid is False
    assert "script tags are not allowed" in result.errors
    assert "inline event handlers are not allowed" in result.errors
    assert "<script" not in result.sanitized_html.lower()


def test_validate_slide_html_rejects_encoded_javascript_urls():
    result = validate_slide_html('<div><a href="java&#115;cript:alert(1)">x</a></div>')

    assert result.valid is False
    assert "javascript urls are not allowed" in result.errors
    assert "javascript:" not in result.sanitized_html.lower()


def test_validate_slide_html_accepts_clean_slide_html():
    result = validate_slide_html('<div style="width:1280px;height:720px"><h1>Hello</h1></div>')

    assert result.valid is True
    assert result.errors == []
    assert "Hello" in result.sanitized_html


def _tool_request(**overrides):
    data = {
        "projectId": "p1",
        "slideIndex": 1,
        "userRequest": "Make the title shorter",
        "slideTitle": "Original",
        "slideContent": '<div style="width:1280px;height:720px"><h1>Long Original Title</h1><p>Body</p></div>',
        "projectInfo": {"title": "Project", "topic": "Topic", "scenario": "Pitch"},
        "slideOutline": {"title": "Original", "content_points": ["Body"]},
    }
    data.update(overrides)
    return SlideEditAgentRequest(**data)


def _tool_context(**overrides):
    request = _tool_request(**overrides)
    return SlideEditAgentContext.from_request(request)


@pytest.mark.asyncio
async def test_tool_runner_inspects_slide_html():
    runner = SlideEditToolRunner(_tool_context())

    result = await runner.execute_tool("inspect_slide_html", {"slide_index": 1})

    assert result["success"] is True
    assert result["tool"] == "inspect_slide_html"
    assert result["headings"][0]["text"] == "Long Original Title"
    assert result["text_blocks"]


@pytest.mark.asyncio
async def test_tool_runner_replace_slide_html_updates_draft_not_base():
    context = _tool_context()
    runner = SlideEditToolRunner(context)
    original_hash = context.base_hash

    result = await runner.execute_tool(
        "replace_slide_html",
        {"html": '<div style="width:1280px;height:720px"><h1>New</h1></div>'},
    )

    assert result["success"] is True
    assert "New" in runner.current_html
    assert context.base_hash == original_hash
    assert "Long Original Title" in context.base_html


@pytest.mark.asyncio
async def test_tool_runner_updates_text_by_selector():
    runner = SlideEditToolRunner(_tool_context())

    result = await runner.execute_tool("update_text", {"selector": "h1", "text": "Short Title"})

    assert result["success"] is True
    assert "Short Title" in runner.current_html
    assert "Long Original Title" not in runner.current_html


@pytest.mark.asyncio
async def test_tool_runner_update_style_uses_css_whitelist():
    runner = SlideEditToolRunner(_tool_context())

    result = await runner.execute_tool(
        "update_style",
        {
            "selector": "h1",
            "styles": {
                "color": "#123456",
                "font-size": "48px",
                "position": "fixed",
                "behavior": "url(bad)",
            },
        },
    )

    assert result["success"] is True
    assert "color: #123456" in runner.current_html
    assert "font-size: 48px" in runner.current_html
    assert "position: fixed" not in runner.current_html
    assert "behavior" not in runner.current_html


@pytest.mark.asyncio
async def test_tool_runner_replaces_element_and_preserves_quick_ai_id_in_draft():
    runner = SlideEditToolRunner(
        _tool_context(
            mode="element",
            selectedElementHtml='<h1 data-quick-ai-id="el1">Long Original Title</h1>',
            selectedElementId="el1",
        )
    )

    result = await runner.execute_tool(
        "replace_element_html",
        {"element_id": "el1", "html": '<h1 data-quick-ai-id="el1">Short Title</h1>'},
    )

    assert result["success"] is True
    assert 'data-quick-ai-id="el1"' in runner.current_html
    assert "Short Title" in runner.current_html


def test_tool_runner_build_proposal_strips_agent_ids():
    runner = SlideEditToolRunner(
        _tool_context(
            slideContent='<div style="width:1280px;height:720px"><h1 data-agent-id="a1">Title</h1></div>'
        )
    )

    proposal = runner.build_proposal("Edited title")

    assert proposal.proposal_id
    assert proposal.summary == "Edited title"
    assert "data-agent-id" not in proposal.html_content
    assert proposal.validation.valid is True
