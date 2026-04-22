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


def test_chat_template_has_collapsible_mobile_search_shell():
    template = _read("templates/template.html")

    assert 'id="mobileSearchToggle"' in template
    assert 'id="mobileSearchPanel"' in template
    assert 'id="mobileControlsToggle"' in template
    assert 'id="mobileSecondaryPanel"' in template
    assert 'aria-label="展开搜索"' in template
    assert 'aria-label="展开更多筛选"' in template


def test_chat_template_uses_icon_buttons_for_search_and_expand_actions():
    template = _read("templates/template.html")

    assert re.search(r'<button id="confirmSearch"[^>]*>\s*<svg', template)
    assert re.search(r'<button id="mobileControlsToggle"[^>]*>\s*<svg', template)


def test_chat_js_controls_mobile_header_state():
    script = _read("static/chat.js")

    assert 'const mobileSearchToggle = document.getElementById(\'mobileSearchToggle\');' in script
    assert 'mobileSearchPanel.classList.toggle(\'is-expanded\'' in script
    assert 'mobileSecondaryPanel.classList.toggle(\'is-open\'' in script


def test_chat_css_animates_mobile_search_panel_from_right():
    css = _read("static/chat.css")

    assert '.mobile-search-shell {' in css
    assert 'transform-origin: right center;' in css
    assert 'transition: width 0.28s ease, opacity 0.2s ease, transform 0.28s ease;' in css
    assert '.mobile-secondary-panel.is-open {' in css


def test_management_template_has_mobile_chat_actions_grid():
    template = _read("templates/index.html")

    assert '.chat-item {' in template
    assert 'flex-direction: column;' in template
    assert 'grid-template-columns: repeat(2, minmax(0, 1fr));' in template
    assert 'grid-column: 1 / -1;' in template
