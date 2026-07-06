# Slide Edit Agent Design

Date: 2026-07-05

## Goal

Convert the current sidebar AI editing assistant from a single-turn "generate HTML and apply" flow into an agent-style PPT editing assistant. The assistant should be able to reason over the current project, choose editing tools, produce validated slide changes, show its progress in the sidebar, and let the user confirm before changes are persisted.

The first implementation should prioritize safe, observable editing of existing slides over broad autonomous behavior.

## Current State

The current sidebar flow is split across these areas:

- `src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.aiChat.js`
  - Sends current slide context to `/api/ai/slide-edit/stream`.
  - Renders streamed assistant text.
  - Extracts returned HTML and adds a manual "apply changes" button.
- `src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.aiApply.js`
  - Applies full-slide HTML into local `slidesData`, iframe preview, thumbnails, code editor, and server save.
- `src/landppt/web/static/js/pages/project/slides_editor/projectSlidesEditor.quickAi.js`
  - Edits a selected element through `/api/ai/element-edit`.
  - Applies returned element HTML directly into the iframe DOM and saves the slide.
- `src/landppt/web/route_modules/ai_edit_routes.py`
  - Contains `/api/ai/slide-edit`, `/api/ai/slide-edit/stream`, `/api/ai/element-edit`, and related AI routes.
- `src/landppt/web/route_modules/slide_routes.py`
  - Contains `/api/projects/{project_id}/slides/{slide_index}/save`, the existing single-slide persistence path.

The existing behavior has three limits:

1. The model returns free-form text and possibly full HTML; the application then tries to extract a code block.
2. There is no planning or tool observation loop, so multi-step requests are fragile.
3. Validation and persistence are not separated from generation clearly enough for safe autonomous editing.

The project already has a ReAct-style pattern in `src/landppt/services/deep_research_service.py`. The edit agent should reuse that pattern conceptually: structured actions, bounded iterations, tool observations, and stream events.

## Recommended Approach

Use a server-side agent loop with explicit PPT editing tools and a user-confirmed apply step.

The agent may inspect slides, select elements, draft HTML changes, run validation, and emit a proposed patch. It must not persist the patch during the reasoning loop. Persistence happens only when the user confirms the proposal from the sidebar.

This gives the product an agentic workflow while preserving editor safety and existing save semantics.

## Non-Goals

- Do not replace the whole slides editor.
- Do not make the first version fully autonomous by default.
- Do not build a new database persistence path for edited slides.
- Do not require browser DOM access from the backend.
- Do not remove the existing quick edit toolbar or manual HTML/code editor flows.

## User Experience

The sidebar remains the primary entry point. The user enters an editing instruction such as "make this slide more visual and simplify the text".

The sidebar then shows a task timeline instead of only token text:

1. Analyzing current slide and outline.
2. Selecting relevant edit tools.
3. Drafting changes.
4. Validating HTML and layout constraints.
5. Ready to preview.

When the agent emits a draft, the user sees these actions:

- Preview
- Apply
- Continue editing
- Discard

Default behavior is confirmation before applying. A later settings-controlled "auto-apply simple edits" mode can be added after the first version is stable.

## Backend Architecture

Add a new service:

`src/landppt/services/slide/slide_edit_agent_service.py`

Responsibilities:

- Build compact editing context from project, slide, outline, selected element, uploaded images, and optional screenshots.
- Run a bounded ReAct-style loop.
- Parse model actions into structured tool calls.
- Execute only registered editing tools.
- Maintain a transcript of thought/action/observation summaries.
- Produce a final draft with changed slide HTML, summary, validation result, and a stable proposal id.

Suggested models:

- `SlideEditAgentRequest`
- `SlideEditAgentContext`
- `SlideEditAction`
- `SlideEditToolResult`
- `SlideEditProposal`
- `SlideEditValidationResult`

The agent should use the existing editor or vision role provider:

- Use `vision_analysis` when visual input is included.
- Use `editor` otherwise.

## Backend Routes

Add these routes to `src/landppt/web/route_modules/ai_edit_routes.py` or a new imported module if the file grows too much:

### `POST /api/ai/slide-edit-agent/stream`

Runs the agent loop and streams events.

Request fields:

- `projectId`
- `slideIndex`
- `userRequest`
- `chatHistory`
- `mode`: `slide` or `element`
- `selectedElementHtml`
- `selectedElementId`
- `slideScreenshot`
- `elementScreenshot`
- `images`
- `maxIterations`

Response is Server-Sent Events.

Event types:

- `agent_start`
- `agent_step`
- `tool_call`
- `tool_result`
- `draft_ready`
- `validation_result`
- `needs_confirmation`
- `error`

### `POST /api/ai/slide-edit-agent/apply`

Persists an approved proposal.

Request fields:

- `proposalId`
- `projectId`
- `slideIndex`
- `expectedBaseHash`
- `htmlContent`
- `slideData`

The route must verify project ownership, verify that the current slide still matches `expectedBaseHash`, and then reuse the existing single-slide save path or the same `DatabaseProjectManager.save_single_slide()` behavior.

### `POST /api/ai/slide-edit-agent/cancel`

Cancels a running agent task if the implementation stores active jobs. If the first implementation runs per request without background task state, this route can return success for UI consistency and be wired to abort the browser request.

## Tool Function Design

The first version should expose a small, deterministic tool set.

Read tools:

- `get_project_context`
  - Returns title, topic, scenario, slide count, and current outline metadata.
- `get_slide`
  - Returns one slide's title, type, content points, metadata, and HTML.
- `list_slides`
  - Returns compact slide summaries for cross-slide requests.
- `inspect_slide_html`
  - Returns a structural summary of headings, text blocks, images, tables, and candidate elements.
- `select_elements`
  - Finds likely target elements by text, tag, role, alt text, or agent-assigned id.

Draft tools:

- `replace_slide_html`
  - Produces a new full-slide HTML draft.
- `replace_element_html`
  - Produces a draft where one selected element is replaced.
- `update_text`
  - Rewrites text content for one or more selected elements.
- `update_style`
  - Applies whitelisted CSS properties to selected elements.
- `insert_element`
  - Inserts an HTML element at a controlled location.
- `delete_element`
  - Removes selected elements from the draft.
- `generate_image_for_slide`
  - Calls existing image generation services and returns an image asset reference.
- `auto_repair_layout`
  - Uses the existing auto layout repair workflow for one slide.

Validation and persistence tools:

- `validate_slide_html`
  - Rejects scripts, inline event handlers, invalid slide dimensions, missing root content, and obvious unsafe URLs.
- `preview_patch`
  - Returns before/after summary, changed element count, and optional compact diff.
- `save_slide`
  - Only available in the apply route, not inside the reasoning loop.

All write-like tools in the agent loop operate on an in-memory draft. They return observations and updated draft state, not persisted database writes.

## Agent Loop

Default maximum iterations: 6.

Allowed range: 2 to 12 for editing. This is intentionally lower than research because each edit loop carries large HTML context.

Each model response should be parsed as JSON:

```json
{
  "thought": "short reason for next action",
  "action": "inspect_slide_html",
  "action_input": {
    "slide_index": 1
  }
}
```

Final response:

```json
{
  "thought": "why the draft is ready",
  "action": "final",
  "action_input": {
    "summary": "what changed",
    "changed_slide_indices": [1],
    "requires_confirmation": true
  }
}
```

The final proposal should include:

- `proposalId`
- `baseHash`
- `summary`
- `changedSlides`
- `htmlContent`
- `validation`
- `toolTranscript`

## Frontend Changes

Update `projectSlidesEditor.aiChat.js`:

- Send requests to `/api/ai/slide-edit-agent/stream`.
- Parse structured SSE events.
- Render timeline cards for agent steps and tools.
- Render draft controls when `draft_ready` arrives.
- Keep existing chat history storage, but store agent summaries rather than raw hidden tool JSON.

Update `projectSlidesEditor.aiApply.js`:

- Add `applyAgentProposal(proposal)` that calls `/api/ai/slide-edit-agent/apply`.
- Reuse the existing local update logic from `applyAIChanges()` after the backend accepts the proposal.
- Save undo state before applying.

Update `projectSlidesEditor.quickAi.js`:

- Keep the current popover UI.
- Route element edits to the same agent endpoint with `mode: "element"`.
- Send `selectedElementHtml`, `selectedElementId`, and optional element screenshot.
- Apply returned element proposal through the same proposal/apply flow.

Update the sidebar template in `project_slides_editor.html`:

- Keep the existing title and input area.
- Add a timeline container inside `#aiChatMessages`.
- Keep upload, vision, free-dialog, and clear-context buttons.

## Safety Rules

- The agent loop cannot persist changes.
- The apply route must verify project ownership through the current authenticated user.
- The apply route must verify `expectedBaseHash` to avoid overwriting newer user edits.
- HTML validation removes or rejects:
  - `<script>` tags
  - inline event handler attributes
  - `javascript:` URLs
  - malformed empty HTML
- Element edits must preserve the selected element id while drafting, then strip temporary agent ids before final save.
- If validation fails, the sidebar should show the error and offer "continue editing" rather than "apply".

## Credits

Charge one `ai_edit` operation per completed agent run that reaches `draft_ready` or a final answer. Do not charge per internal tool call in the first version. If image generation is invoked, keep existing image operation billing rules.

## Persistence

The final save must reuse the existing single-slide persistence behavior:

- frontend local state update
- iframe preview update
- thumbnail update
- code editor update
- `/api/projects/{project_id}/slides/{slide_index}/save`
- `DatabaseProjectManager.save_single_slide()`

The agent apply route can either call the same internal save logic directly or return an accepted proposal that the frontend saves through `saveSingleSlideToServer()`. The safer first implementation is backend apply plus frontend local sync, because the backend can enforce `baseHash` before writing.

## Testing Plan

Backend tests:

- Agent loop executes model-selected tools in order.
- Unsupported tool names produce tool error observations.
- Max iteration limit stops the loop predictably.
- Draft tools do not call database persistence.
- Apply route rejects mismatched `baseHash`.
- Apply route saves only the requested slide.
- HTML validator rejects scripts and inline event handlers.
- Element mode preserves and then strips temporary element ids.

Frontend/manual checks:

- Sidebar shows agent step events.
- Draft can be previewed before applying.
- Applying updates preview, thumbnail, code editor, and saved slide.
- Discard leaves current slide unchanged.
- Element AI popover can edit a selected text block.
- Vision mode still attaches screenshots.

## Rollout Plan

Phase 1:

- Add backend service, schemas, tools, and tests.
- Add stream route and apply route.
- Keep existing `/api/ai/slide-edit/stream` untouched as fallback.

Phase 2:

- Wire sidebar to the agent endpoint.
- Render timeline events and proposal controls.
- Keep old HTML extraction apply button behind a fallback path.

Phase 3:

- Route quick element AI through the agent.
- Add optional "continue editing this draft" loop.
- Add settings for max iterations and simple-edit auto-apply only after validation is reliable.

## Success Criteria

- A user can ask for a multi-step edit and see the assistant inspect, modify, validate, preview, and apply the result.
- Agent changes are not persisted until the user confirms.
- Existing manual editing, quick editing, image upload, and vision mode continue to work.
- Tests cover the agent loop, tool dispatch, validation, and save boundary.
