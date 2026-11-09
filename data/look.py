"""The look of the app: "calm ledger, friendly household". The colour and shape tokens (light and dark: colours, hero, sheet
shadow, corner radii) that the web app serves as CSS variables (/tokens.css), the chart colours, and each person's light / dark choice, remembered in
config/dashboard_prefs.json (the file name is kept so a choice made earlier still applies).
"""
import json

import config
import paths

PREFS = paths.CONFIG / "dashboard_prefs.json"
TOKENS = {
    # Calm ledger (owner, 2026-11-05): cool grey canvas, white cards, hairlines and one green accent by day, the same
    # tokens deepened for night. The accent text green is a shade darker than the old #2E8B57 so it reads 4.5:1 on white.
    # Every text pair 4.5:1 or more (tests/test_look.py).
    "light": {"canvas": "#F3F4F6", "surface": "#FFFFFF", "surface-2": "#F9FAFB", "line": "#E4E6EA", "text": "#1F2328",
              "text-2": "#5B6470", "accent": "#247A49", "on-accent": "#FFFFFF", "accent-soft": "#E6F4EC", "link": "#0F6CBD",
              "ok": "#1E7F3F", "ok-soft": "#DFF3E6", "warn": "#9A6700", "warn-soft": "#FFF4CC",
              "danger": "#B42318", "danger-soft": "#FCE8E6", "info": "#0F6CBD", "info-soft": "#E3F0FB",
              "neutral-soft": "#EEF0F3", "shadow": "0 1px 2px rgba(16,24,40,.06)",
              "hero": "#E6F4EC", "hero-text": "#1F2328", "sheet-shadow": "0 -8px 24px rgba(16,24,40,.16)",
              "radius": "12px", "radius-sm": "8px", "title-font": "inherit"},
    "dark": {"canvas": "#141516", "surface": "#1E1F21", "surface-2": "#26272A", "line": "#34363A", "text": "#ECEDEE",
             "text-2": "#A3A9B3", "accent": "#4CAF78", "on-accent": "#0B1F14", "accent-soft": "#1E3A2C", "link": "#4DA3FF",
             "ok": "#5BC27E", "ok-soft": "#173826", "warn": "#E0B14A", "warn-soft": "#3A2F12",
             "danger": "#F0756A", "danger-soft": "#3C1C19", "info": "#4DA3FF", "info-soft": "#15304A",
             "neutral-soft": "#2C2E32", "shadow": "0 0 0 1px #34363A",
             "hero": "#1E3A2C", "hero-text": "#ECEDEE", "sheet-shadow": "0 -8px 24px rgba(0,0,0,.5)",
             "radius": "12px", "radius-sm": "8px", "title-font": "inherit"},
}
CHART = ["#2E8B57", "#0F6CBD", "#B8540B", "#7A3DB8", "#00838F", "#C2185B"]
# Person avatars (white initials on these, contrast 4.5:1 or better) and the House's; same in light and dark.
PEOPLE = ["#2E7D52", "#0F6CBD", "#A14A0A", "#7A3DB8", "#00727D", "#B0164F"]
HOUSE = "#5B6470"


def _load():
    try:
        return json.loads(PREFS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def mode_for(user):
    """'light' or 'dark' for this person (their own choice, else the household's, else light)."""
    prefs = _load()
    who = (user or {}).get("name") or "_default"
    m = (prefs.get(who) or prefs.get("_default") or {}).get("theme")
    return m if m in TOKENS else "light"


def remember(user, mode):
    if mode not in TOKENS:
        return
    prefs = _load()
    prefs[(user or {}).get("name") or "_default"] = {"theme": mode}
    config.write_json(PREFS, prefs)
