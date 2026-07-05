import json

from landppt.services.slide.slide_edit_agent_service import (
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
