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


def test_chat_template_has_collapsed_mobile_search_trigger_and_expand_panel():
    template = _read("templates/template.html")

    assert 'id="mobileSearchTrigger"' in template
    assert 'id="mobileSearchExpanded"' in template
    assert 'id="mobileSearchPanel"' in template
    assert 'aria-label="展开搜索"' in template
    assert 'aria-label="展开更多筛选"' in template


def test_chat_template_uses_icon_buttons_for_search_actions():
    template = _read("templates/template.html")

    assert re.search(r'<button id="mobileSearchTrigger"[^>]*>\s*<svg', template)
    assert re.search(r'<button id="confirmSearch"[^>]*>\s*<svg', template)
    assert re.search(r'<button id="mobileControlsToggle"[^>]*>\s*<svg', template)


def test_chat_js_controls_mobile_search_expand_state():
    script = _read("static/chat.js")

    assert "const mobileSearchTrigger = document.getElementById('mobileSearchTrigger');" in script
    assert "mobileSearchExpanded.classList.toggle('is-visible'" in script
    assert "mobileSearchTrigger.classList.toggle('is-hidden'" in script
    assert "mobileSearchPanel.classList.toggle('is-open'" in script


def test_chat_css_uses_transparent_default_header_and_left_expand_animation():
    css = _read("static/chat.css")

    assert '#header.is-collapsed {' in css
    assert 'background: transparent;' in css
    assert '.mobile-search-expanded.is-visible {' in css
    assert 'transform-origin: right center;' in css
    assert 'translateX(0)' in css


def test_management_template_has_mobile_chat_actions_grid():
    template = _read("templates/index.html")

    assert '.chat-item {' in template
    assert 'flex-direction: column;' in template
    assert 'grid-template-columns: repeat(2, minmax(0, 1fr));' in template
    assert 'grid-column: 1 / -1;' in template
