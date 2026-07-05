from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from landppt.services.slide.slide_edit_agent_service import (
    SlideEditAgentApplyRequest,
    SlideEditAgentRequest,
    compute_slide_html_hash,
)
from landppt.web.route_modules import slide_edit_agent_routes as routes


class _FakeProjectManager:
    def __init__(self, project):
        self.project = project

    async def get_project(self, project_id, user_id=None):
        return self.project


class _FakePPTService:
    def __init__(self, project=None):
        self.project_manager = _FakeProjectManager(project)

    async def get_role_provider_async(self, role):
        return None, {"provider": "landppt"}


async def _collect_stream_body(response):
    chunks = []
    async for chunk in response.body_iterator:
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8")
        chunks.append(chunk)
    return "".join(chunks)


@pytest.mark.asyncio
async def test_apply_agent_proposal_rejects_base_hash_mismatch(monkeypatch):
    project = SimpleNamespace(
        slides_data=[
            {
                "title": "One",
                "html_content": "<div>Current</div>",
                "is_user_edited": False,
            }
        ]
    )
    monkeypatch.setattr(
        routes, "get_ppt_service_for_user", lambda user_id: _FakePPTService(project)
    )

    request = SlideEditAgentApplyRequest(
        proposalId="p1",
        projectId="proj",
        slideIndex=1,
        expectedBaseHash=compute_slide_html_hash("<div>Old</div>"),
        htmlContent="<div>New</div>",
        slideData={"title": "One"},
    )

    with pytest.raises(HTTPException) as exc:
        await routes.apply_slide_edit_agent_proposal(
            request, user=SimpleNamespace(id=10)
        )

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_apply_agent_proposal_saves_only_target_slide(monkeypatch):
    current_html = '<div style="width:1280px;height:720px"><h1>Current</h1></div>'
    project = SimpleNamespace(
        slides_data=[
            {"title": "One", "html_content": current_html, "is_user_edited": False},
            {
                "title": "Two",
                "html_content": "<div>Second</div>",
                "is_user_edited": False,
            },
        ]
    )
    saved = {}

    class _FakeDBManager:
        async def save_single_slide(self, project_id, slide_index, slide_data):
            saved["project_id"] = project_id
            saved["slide_index"] = slide_index
            saved["slide_data"] = slide_data
            return True

    monkeypatch.setattr(
        routes, "get_ppt_service_for_user", lambda user_id: _FakePPTService(project)
    )
    monkeypatch.setattr(routes, "DatabaseProjectManager", lambda: _FakeDBManager())

    request = SlideEditAgentApplyRequest(
        proposalId="p1",
        projectId="proj",
        slideIndex=1,
        expectedBaseHash=compute_slide_html_hash(current_html),
        htmlContent='<div style="width:1280px;height:720px"><h1>New</h1></div>',
        slideData={"title": "One"},
    )

    result = await routes.apply_slide_edit_agent_proposal(
        request, user=SimpleNamespace(id=10)
    )

    assert result["success"] is True
    assert saved["project_id"] == "proj"
    assert saved["slide_index"] == 0
    assert saved["slide_data"]["title"] == "One"
    assert "New" in saved["slide_data"]["html_content"]
    assert saved["slide_data"]["is_user_edited"] is True


@pytest.mark.asyncio
async def test_stream_slide_edit_agent_charges_once_after_draft(monkeypatch):
    charges = []

    class _FakeAgentService:
        async def run_agent(self, request, user_ppt_service, event_callback):
            await event_callback({"type": "agent_start"})
            await event_callback(
                {"type": "draft_ready", "proposal": {"proposalId": "p1"}}
            )
            await event_callback({"type": "needs_confirmation", "proposalId": "p1"})
            return SimpleNamespace(proposal_id="p1")

    async def check_credits(*args, **kwargs):
        return True, 1, 10

    async def consume_credits(*args, **kwargs):
        charges.append({"args": args, "kwargs": kwargs})
        return True, "ok"

    monkeypatch.setattr(
        routes, "get_ppt_service_for_user", lambda user_id: _FakePPTService()
    )
    monkeypatch.setattr(routes, "check_credits_for_operation", check_credits)
    monkeypatch.setattr(routes, "consume_credits_for_operation", consume_credits)
    monkeypatch.setattr(routes, "SlideEditAgentService", _FakeAgentService)

    response = await routes.stream_slide_edit_agent(
        SlideEditAgentRequest(
            projectId="proj",
            slideIndex=1,
            slideTitle="One",
            slideContent="<div>Current</div>",
            userRequest="Shorten the title",
        ),
        user=SimpleNamespace(id=10),
    )

    body = await _collect_stream_body(response)

    assert '"type": "draft_ready"' in body
    assert len(charges) == 1
    assert charges[0]["args"][:3] == (10, "ai_edit", 1)
    assert charges[0]["kwargs"]["reference_id"] == "proj"


@pytest.mark.asyncio
async def test_stream_slide_edit_agent_does_not_charge_without_draft(monkeypatch):
    charges = []

    class _FakeAgentService:
        async def run_agent(self, request, user_ppt_service, event_callback):
            await event_callback({"type": "agent_start"})
            raise RuntimeError("model unavailable")

    async def check_credits(*args, **kwargs):
        return True, 1, 10

    async def consume_credits(*args, **kwargs):
        charges.append({"args": args, "kwargs": kwargs})
        return True, "ok"

    monkeypatch.setattr(
        routes, "get_ppt_service_for_user", lambda user_id: _FakePPTService()
    )
    monkeypatch.setattr(routes, "check_credits_for_operation", check_credits)
    monkeypatch.setattr(routes, "consume_credits_for_operation", consume_credits)
    monkeypatch.setattr(routes, "SlideEditAgentService", _FakeAgentService)

    response = await routes.stream_slide_edit_agent(
        SlideEditAgentRequest(
            projectId="proj",
            slideIndex=1,
            slideContent="<div>Current</div>",
            userRequest="Shorten the title",
        ),
        user=SimpleNamespace(id=10),
    )

    body = await _collect_stream_body(response)

    assert '"type": "error"' in body
    assert "model unavailable" in body
    assert charges == []


@pytest.mark.asyncio
async def test_cancel_slide_edit_agent_returns_success():
    result = await routes.cancel_slide_edit_agent(user=SimpleNamespace(id=10))

    assert result == {"success": True}
