"""Accessibility checks from the 28 Oct 2026 audit (WCAG 2.1 AA): text contrast of the colour tokens, a visible keyboard
focus ring, no menu roles without menu keys, status lines a screen reader can read, story cards usable without a pointer."""
import re

from test_webapp import _login, web  # noqa: F401 (the web fixture)


def _lum(h):
    c = [int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def ratio(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def test_text_tokens_meet_4_5_to_1(modules):
    look = modules("look")
    for mode, t in look.TOKENS.items():
        for fg, bg in (("text", "canvas"), ("text", "surface"), ("text-2", "canvas"), ("text-2", "surface"),
                       ("hero-text", "hero"), ("on-accent", "accent"), ("accent", "canvas")):
            assert ratio(t[fg], t[bg]) >= 4.5, f"{mode}: {fg} on {bg} is {ratio(t[fg], t[bg]):.2f}:1"


def test_keyboard_focus_ring_is_solid(root):
    css = (root / "data" / "webapp" / "static" / "app.css").read_text(encoding="utf-8")
    rule = re.search(r"\.btn:focus-visible,\.primary:focus-visible,\.ghost:focus-visible\{([^}]*)\}", css).group(1)
    assert "outline:2px solid var(--accent)" in rule and "outline:none" not in rule
    assert "input:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid var(--accent)" in css
    assert ".hero .sub{color:inherit}" in css, "no faded subtitle on the banner"


def test_more_menu_has_no_menu_roles(web):  # noqa: F811
    c, _, _ = web
    _login(c)
    page = c.get("/").text
    assert 'role="menu"' not in page and 'role="menuitem"' not in page, "a disclosure of links, not an ARIA menu"


def test_wall_status_lines_are_always_in_the_page(root):
    base = (root / "data" / "webapp" / "templates" / "wall_base.html").read_text(encoding="utf-8")
    assert '<p class="alert" id="wmsg" role="status"></p>' in base and '<p class="woff" id="woff" role="status"></p>' in base
    js = (root / "data" / "webapp" / "static" / "wall.js").read_text(encoding="utf-8")
    assert "box.hidden" not in js, "text changes inside a present status line; hiding it hides it from screen readers"
    css = (root / "data" / "webapp" / "static" / "wall.css").read_text(encoding="utf-8")
    assert ".flip .fd.flip { animation: none" in css.replace(".st-kenburns .ph, ", ""), "the flip clock honours reduced motion"


def test_story_cards_have_buttons_and_a_position(root):
    js = (root / "data" / "webapp" / "static" / "app.js").read_text(encoding="utf-8")
    assert "'Previous card'" in js and "'Next card'" in js and "' of ' + slides.length" in js


def test_story_buttons_use_theme_colours_and_their_own_class(root, modules):
    css = (root / "data" / "webapp" / "static" / "app.css").read_text(encoding="utf-8")
    assert re.search(r"(^|\n)\.snav\{", css) is None, "`.snav` is the Money month links; the story buttons' box is .story-nav"
    assert "nav.className = 'story-nav'" in (root / "data" / "webapp" / "static" / "app.js").read_text(encoding="utf-8")
    rule = re.search(r"\n\.snav-b\{([^}]*)\}", css).group(1)
    assert "background:var(--surface-2)" in rule and "color:var(--text)" in rule and "solid var(--text-2)" in rule
    assert ".snav-b:focus-visible{outline:2px solid var(--accent)" in css
    for mode, t in modules("look").TOKENS.items():  # the card is --surface: the button edge and the focus ring show on it
        assert ratio(t["text-2"], t["surface"]) >= 3 and ratio(t["accent"], t["surface"]) >= 3, mode
        assert ratio(t["text"], t["surface-2"]) >= 4.5, mode
