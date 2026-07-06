import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_editor_slideshow_shield_does_not_block_slide_interactions():
    template = _read("src/landppt/web/templates/pages/project/project_slides_editor.html")
    css = _read("src/landppt/web/static/css/pages/project/slides_editor/projectSlidesEditor.css")

    assert 'id="slideshowShield"' in template
    assert re.search(
        r"\.slideshow-shield\s*\{[^}]*pointer-events\s*:\s*none",
        css,
        flags=re.DOTALL,
    )
