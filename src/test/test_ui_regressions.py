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


def test_chat_css_last_body_rule_does_not_dim_bg_png_with_gradient_overlay():
    css = _read("static/chat.css")
    body_rules = re.findall(r"body\s*\{.*?\}", css, flags=re.S)

    assert body_rules, "expected at least one body CSS rule"
    assert "linear-gradient" not in body_rules[-1]


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


def test_chat_js_does_not_force_desktop_header_open_by_default():
    script = _read("static/chat.js")

    assert "mobileSearchExpanded.classList.add('is-visible');" not in script
    assert "mobileSearchPanel.classList.add('is-open');" not in script
    assert "mobileSearchTrigger.classList.remove('is-hidden');" not in script


def test_chat_css_uses_transparent_default_header_and_left_expand_animation():
    css = _read("static/chat.css")

    assert '#header.is-collapsed {' in css
    assert 'background: transparent;' in css
    assert '.mobile-search-expanded.is-visible {' in css
    assert 'transform-origin: right center;' in css
    assert 'translateX(0)' in css


def test_chat_css_keeps_collapsed_trigger_right_aligned_on_mobile():
    css = _read("static/chat.css")

    assert re.search(r"body #header\s*\{[^}]*justify-content:\s*flex-end;", css, flags=re.S)


def test_chat_css_gives_search_action_buttons_their_own_fixed_columns():
    css = _read("static/chat.css")

    assert re.search(r"#confirmSearch\s*,\s*#mobileControlsToggle\s*\{[^}]*width:\s*42px;", css, flags=re.S)
    assert re.search(r"#confirmSearch\s*,\s*#mobileControlsToggle\s*\{[^}]*margin-left:\s*0;", css, flags=re.S)


def test_chat_css_does_not_force_mobile_search_icon_button_to_expand_to_88px():
    css = _read("static/chat.css")

    assert not re.search(r"body #confirmSearch\s*,\s*body #downloadBrokenImages", css, flags=re.S)
    assert re.search(r"@media screen and \(max-width: 768px\)\s*\{.*?#confirmSearch\s*,\s*#mobileControlsToggle\s*\{[^}]*min-width:\s*42px;[^}]*max-width:\s*42px;", css, flags=re.S)


def test_management_template_has_mobile_chat_actions_grid():
    template = _read("templates/index.html")

    assert '.chat-item {' in template
    assert 'flex-direction: column;' in template
    assert 'grid-template-columns: repeat(2, minmax(0, 1fr));' in template
    assert 'grid-column: 1 / -1;' in template
