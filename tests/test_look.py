"""The look: theme helpers, readable table headings, money columns, and the one empty state for Vehicles."""


def test_labels_are_words_not_column_names(modules):
    R = modules("records")
    assert R.column_label("appt_datetime") == "When"
    assert R.column_label("due_date") == "Due"
    assert R.column_label("birth_year") == "Born"
    assert R.column_label("some_new_column") == "Some new column"
    assert R.column_label("who") == "Who"


def test_money_parts_are_grouped_once(modules):
    R = modules("records")
    grouped = [k for _, ks in R.GROUPS["money"] for k in ks]
    assert sorted(grouped) == sorted(k for k, _ in R.SECTIONS["money"]), "every Money part is in exactly one group"


def _contrast(a, b):
    def lum(h):
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
        f = (lambda c: c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4)
        return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)
    la, lb = lum(a), lum(b)
    return (max(la, lb) + .05) / (min(la, lb) + .05)


def test_text_and_filled_buttons_meet_aa_contrast_in_both_themes(modules):
    look = modules("look")
    pairs = [("on-accent", "accent"), ("text", "canvas"), ("text", "surface"), ("text-2", "surface"), ("text-2", "canvas"),
             ("accent", "surface"), ("accent", "accent-soft"), ("link", "surface"), ("danger", "surface")]
    for mode, t in look.TOKENS.items():
        for fg, bg in pairs:
            assert _contrast(t[fg], t[bg]) >= 4.5, f"{mode}: {fg} on {bg} is {_contrast(t[fg], t[bg]):.1f}:1"


def test_accent_filled_controls_use_the_on_accent_colour(root):
    import re
    css = (root / "data" / "webapp" / "static" / "app.css").read_text(encoding="utf-8")
    bad = [b for b in re.findall(r"\{[^{}]*\}", css) if "background:var(--accent)" in b and "color:#fff" in b]
    assert bad == [], "white text on the accent fails in dark mode: use var(--on-accent)"


def test_hero_text_and_the_button_focus_ring_are_readable(root, modules):
    """audit 2026-10-28 (WCAG 2.1 AA): white on the hero green was 4.25:1 and the button focus ring (a pale halo) 1.04:1"""
    look = modules("look")
    for mode in ("light", "dark"):
        t = look.TOKENS[mode]
        assert _contrast(t["hero"], t["hero-text"]) >= 4.5, mode
    css = (root / "data" / "webapp" / "static" / "app.css").read_text(encoding="utf-8")
    rule = next(r for r in css.splitlines() if r.startswith(".btn:focus-visible"))
    assert "outline:2px solid var(--accent)" in rule and "box-shadow:0 0 0 3px var(--accent-soft)" not in rule
    for mode in ("light", "dark"):
        t = look.TOKENS[mode]
        assert _contrast(t["accent"], t["surface"]) >= 3, f"the focus ring needs 3:1 against the page ({mode})"
