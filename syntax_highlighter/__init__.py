"""
Syntax Highlighter for Anki  (v1.2.0)
--------------------------------------
Compatible: Anki 2.1.45+ / 25.x (PyQt6), Windows / macOS / Linux

Hooks used:
  * gui_hooks.add_cards_will_add_note  -- intercepts new notes in Add dialog
  * gui_hooks.editor_did_init_buttons  -- adds </> HL toolbar button
  * gui_hooks.profile_did_open         -- creates Code-Standard note type

Formatting:
  * Uses Pygments nowrap=True to take full control of the HTML wrapper.
  * Newlines converted to <br> so Anki's field storage never collapses them.
  * Indentation preserved via white-space:pre-wrap on the container div.
  * Background color sourced from the active Pygments theme automatically.
"""

import sys
import os

# ---------------------------------------------------------------------------
# Bundled Pygments -- loaded from ./lib/ so users need no pip install
# ---------------------------------------------------------------------------
_ADDON_DIR = os.path.dirname(__file__)
_LIB_DIR   = os.path.join(_ADDON_DIR, "lib")
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

from aqt import mw, gui_hooks
from aqt.editor import Editor
from aqt.utils import showInfo, tooltip

from pygments import highlight
from pygments.lexers import get_lexer_by_name, TextLexer
from pygments.formatters import HtmlFormatter
from pygments.util import ClassNotFound

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
NOTE_TYPE_NAME = "Code-Standard"
FIELD_LANGUAGE = "Language"
FIELD_CODE     = "Code"

# Short aliases that Pygments doesn't recognise natively
LANGUAGE_ALIASES = {
    "py":         "python",
    "js":         "javascript",
    "ts":         "typescript",
    "rb":         "ruby",
    "c++":        "cpp",
    "c#":         "csharp",
    "sh":         "bash",
    "shell":      "bash",
    "yml":        "yaml",
    "dockerfile": "docker",
    "txt":        "text",
    "plain":      "text",
}

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _cfg() -> dict:
    return mw.addonManager.getConfig(__name__) or {}

def _theme() -> str:
    return _cfg().get("theme", "monokai")

def _font_size() -> str:
    return _cfg().get("font_size", "0.88em")

def _line_height() -> str:
    return _cfg().get("line_height", "1.6")

def _tab_size() -> int:
    return int(_cfg().get("tab_size", 4))

# ---------------------------------------------------------------------------
# Lexer resolution
# ---------------------------------------------------------------------------

def _resolve_lexer(lang: str):
    """Map user input to a Pygments lexer; fall back to TextLexer silently."""
    lang = lang.strip().lower()
    lang = LANGUAGE_ALIASES.get(lang, lang)
    if not lang:
        return TextLexer(stripall=True)
    try:
        return get_lexer_by_name(lang, stripall=True)
    except ClassNotFound:
        return TextLexer(stripall=True)

# ---------------------------------------------------------------------------
# Already-highlighted guard
# ---------------------------------------------------------------------------

def _already_highlighted(html: str) -> bool:
    """
    Return True if the field already contains highlighted HTML.
    Prevents double-processing which would produce broken nested markup.
    """
    return (
        'data-pygments="1"' in html   # our own marker (v1.2+)
        or '<span style=' in html      # inline-style spans from older version
        or '<span class=' in html      # class-based spans from older version
    )

# ---------------------------------------------------------------------------
# HTML formatter  -- the core of whitespace/newline preservation
# ---------------------------------------------------------------------------

def _build_highlighted_html(raw_code: str, lang: str) -> str:
    """
    Tokenise raw_code and return a self-contained HTML block that:
      - preserves all indentation (spaces and tabs)
      - preserves blank lines
      - wraps long lines without breaking indentation logic
      - works in Anki's card renderer on desktop, AnkiMobile, and AnkiDroid
      - carries a data-pygments marker so the guard above can detect it

    Strategy:
      1. Use nowrap=True so Pygments returns bare <span>...</span> tokens
         with no <pre> or <div> wrapper (we build our own).
      2. Replace tab characters with non-breaking spaces before tokenising
         so indentation is never collapsed by HTML renderers.
      3. Convert newline characters to <br> tags so Anki's field storage
         (which serialises HTML into SQLite) cannot collapse them.
      4. Wrap everything in a single <div> whose style provides:
             font-family : monospace stack
             white-space : pre-wrap   (honours our spaces; wraps at viewport)
             word-break  : break-all  (stops very long tokens from overflowing)
             line-height : configurable (default 1.6 for readability)
             background  : pulled from the active Pygments theme
    """
    theme   = _theme()
    lexer   = _resolve_lexer(lang)

    # Expand tabs to non-breaking spaces so HTML renderers preserve indentation
    tab_stop   = _tab_size()
    nbsp_block = "\u00a0" * tab_stop          # U+00A0 = &nbsp;
    raw_code   = raw_code.replace("\t", nbsp_block)

    # Also replace leading runs of spaces with &nbsp; chains so browsers
    # don't collapse them (some Anki WebView builds do collapse plain spaces)
    import re
    def _protect_leading_spaces(m):
        return "\u00a0" * len(m.group(0))
    raw_code = re.sub(r"(?m)^ +", _protect_leading_spaces, raw_code)

    formatter = HtmlFormatter(
        noclasses=True,   # inline styles -> works everywhere, no extra CSS
        style=theme,
        nowrap=True,      # skip Pygments' <pre>/<div>; we build our own
        stripnl=False,    # keep the final newline token
    )

    inner_html = highlight(raw_code, lexer, formatter)

    # Convert newlines to <br> tags (critical for Anki field storage)
    inner_html = inner_html.replace("\n", "<br>")

    # Pull background colour from the theme so the div matches exactly
    bg_color = formatter.style.background_color or "#1e1e1e"

    # Determine a contrasting default text colour from theme
    default_color = formatter.style.style_for_token(
        __import__("pygments.token", fromlist=["Token"]).Token.Text
    ).get("color") or ""
    text_color = ("#" + default_color) if default_color else "#f8f8f2"

    container = (
        '<div'
        ' data-pygments="1"'
        ' style="'
        f'background:{bg_color};'
        f'color:{text_color};'
        'border-radius:6px;'
        'padding:14px 16px;'
        'margin:8px 0;'
        'overflow-x:auto;'
        f'font-family:\'Fira Code\',\'Cascadia Code\',\'Consolas\',monospace;'
        f'font-size:{_font_size()};'
        f'line-height:{_line_height()};'
        'white-space:pre-wrap;'
        'word-break:break-all;'
        'text-align:left;'
        '">'
        f'{inner_html}'
        '</div>'
    )

    return container

# ---------------------------------------------------------------------------
# Note-level processing
# ---------------------------------------------------------------------------

def _get_model_name(note) -> str:
    try:
        return note.note_type()["name"]
    except Exception:
        try:
            return note.model()["name"]
        except Exception:
            return ""


def process_note(note, force: bool = False) -> bool:
    """
    Highlight the Code field in-place.
    Returns True when highlighting was applied.
    force=True bypasses the already-highlighted guard (for the toolbar button).
    """
    if _get_model_name(note) != NOTE_TYPE_NAME:
        return False

    try:
        raw_code = note[FIELD_CODE]
        lang_raw = note[FIELD_LANGUAGE]
    except KeyError:
        return False

    # Strip HTML that Anki's rich-text editor may have injected
    # (e.g. <div>, <br>, <p> tags the user didn't type)
    import re
    clean_code = re.sub(r"<br\s*/?>", "\n", raw_code, flags=re.IGNORECASE)
    clean_code = re.sub(r"<div[^>]*>", "\n", clean_code, flags=re.IGNORECASE)
    clean_code = re.sub(r"</div>", "", clean_code, flags=re.IGNORECASE)
    clean_code = re.sub(r"<p[^>]*>", "\n", clean_code, flags=re.IGNORECASE)
    clean_code = re.sub(r"</p>", "", clean_code, flags=re.IGNORECASE)
    clean_code = re.sub(r"<[^>]+>", "", clean_code)   # strip remaining tags
    # Decode common HTML entities
    clean_code = (clean_code
                  .replace("&amp;",  "&")
                  .replace("&lt;",   "<")
                  .replace("&gt;",   ">")
                  .replace("&nbsp;", " ")
                  .replace("&quot;", '"'))
    clean_code = clean_code.strip()

    if not force and _already_highlighted(raw_code):
        return False

    if not clean_code:
        return False

    try:
        highlighted = _build_highlighted_html(clean_code, lang_raw)
    except Exception as exc:
        print(f"[SyntaxHighlighter] Error: {exc}")
        return False

    note[FIELD_CODE] = highlighted
    return True

# ---------------------------------------------------------------------------
# Hook: Add Cards dialog
# Signature (filter): (problem: Optional[str], note: Note) -> Optional[str]
# ---------------------------------------------------------------------------

def _on_add_cards_will_add_note(problem, note):
    if problem is None:        # only process notes that passed validation
        process_note(note)
    return problem             # always pass the problem value through unchanged

gui_hooks.add_cards_will_add_note.append(_on_add_cards_will_add_note)

# ---------------------------------------------------------------------------
# Hook: Editor toolbar button
# Works in the Add dialog, the Browse window, and Edit Current.
# ---------------------------------------------------------------------------

def _do_highlight(editor: Editor) -> None:
    note = editor.note
    if note is None:
        return

    applied = process_note(note, force=True)

    if not applied:
        if _get_model_name(note) != NOTE_TYPE_NAME:
            tooltip("Not a Code-Standard note — nothing to highlight.")
        else:
            tooltip("Code field is empty or already processed.")
        return

    # Persist back to the collection (no-op if note is brand-new / unsaved)
    try:
        mw.col.update_note(note)
    except Exception:
        pass

    # Reload the editor so the field display reflects the new HTML
    editor.load_note(focusTo=None)
    tooltip("✅ Code highlighted!")


def _highlight_btn_clicked(editor: Editor) -> None:
    # call_after_note_saved flushes the webview into note fields first
    editor.call_after_note_saved(
        lambda: _do_highlight(editor),
        keepFocus=True,
    )


def _add_highlight_button(buttons: list, editor: Editor) -> None:
    btn = editor.addButton(
        icon=None,
        cmd="syntaxHighlight",
        func=_highlight_btn_clicked,
        tip="Apply syntax highlighting (Syntax Highlighter add-on)",
        label="</> HL",
    )
    buttons.append(btn)


gui_hooks.editor_did_init_buttons.append(_add_highlight_button)

# ---------------------------------------------------------------------------
# Bootstrap: create Code-Standard note type on first profile load
# ---------------------------------------------------------------------------

def _ensure_note_type() -> None:
    col = mw.col
    if col is None:
        return
    if col.models.by_name(NOTE_TYPE_NAME):
        return

    mm = col.models
    m  = mm.new(NOTE_TYPE_NAME)

    for fname in (FIELD_LANGUAGE, FIELD_CODE, "Tags"):
        mm.add_field(m, mm.new_field(fname))

    t = mm.new_template("Card 1")
    t["qfmt"] = (
        "<div style='font-family:monospace;font-size:0.8em;"
        "color:#aaa;padding:4px 8px;'>{{" + FIELD_LANGUAGE + "}}</div>"
        "{{" + FIELD_CODE + "}}"
    )
    t["afmt"] = (
        "{{FrontSide}}<hr id=answer>"
        "<div style='color:#888;font-size:0.75em;'>{{Tags}}</div>"
    )
    mm.add_template(m, t)

    m["css"] = (
        ".card {\n"
        "  background: #1a1a1a;\n"
        "  color: #f8f8f2;\n"
        "  font-family: sans-serif;\n"
        "  padding: 12px;\n"
        "  text-align: left;\n"
        "}\n"
        "[data-pygments] {\n"
        "  /* Highlighted code blocks */\n"
        "  display: block;\n"
        "  text-align: left;\n"
        "}\n"
    )

    mm.add(m)
    showInfo(
        "Syntax Highlighter: Created the 'Code-Standard' note type.\n\n"
        "Fields:\n"
        "  • Language  – e.g. python, javascript, sql, cpp\n"
        "  • Code      – paste raw un-highlighted code here\n"
        "  • Tags      – optional Anki tags\n\n"
        "Hit Add (or click </> HL) to highlight."
    )


gui_hooks.profile_did_open.append(_ensure_note_type)