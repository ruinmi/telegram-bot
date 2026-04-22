from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8-sig")


def test_chat_css_last_body_rule_keeps_bg_png_background():
    css = _read("static/chat.css")
    body_rules = re.findall(r"body\s*\{.*?\}", css, flags=re.S)

    assert body_rules, "expected at least one body CSS rule"
    assert "url('resources/bg.png')" in body_rules[-1]


def test_chat_template_has_mobile_header_wrappers():
    template = _read("templates/template.html")

    assert 'class="header-search-row"' in template
    assert 'class="header-filters"' in template


def test_management_template_has_mobile_chat_actions_grid():
    template = _read("templates/index.html")

    assert '.chat-item {' in template
    assert 'flex-direction: column;' in template
    assert 'grid-template-columns: repeat(2, minmax(0, 1fr));' in template
    assert 'grid-column: 1 / -1;' in template
