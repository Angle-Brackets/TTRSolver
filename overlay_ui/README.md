# Overlay UI

The page shown in the live advice panel. It is a React app styled with
Tailwind and daisyUI, displayed in a pywebview window by one of two
Python programs:

- `solver/live/panel.py`, the Toontown Rewritten (TTR) panel
- `solver/live/realms_panel.py`, the Toontown Realms panel

Both render this same build. To use the panel as a player, read the
[user guide](../docs/user-guide.md).

## Running it

```
pip install pywebview
python -m solver.live.panel
```

or `python run.py` and pick the TTR overlay. The TTR panel also needs
`requirements-vision.txt` for its screen reader.

**No Node.js is needed to run it.** `dist/` is committed. If `dist/` is
missing, the panel prints the build command and exits instead of opening
a blank window.

## Changing it

```
cd overlay_ui
npm install
npm run dev      # hot reload in a browser, no Python
npm run build    # writes dist/, which must be committed
```

`npm run dev` is useful on its own. With no Python behind it the page
renders its empty defaults, and calling `window.pushModel({...})` from the
browser console puts it in any state you want to look at. Button clicks
do nothing there, because `window.pywebview` is absent.

| Path | What it is |
|---|---|
| `src/App.jsx` | The whole panel: the move card, engine rows, cog rows, settings, feedback strip. |
| `src/CogPicker.jsx` | The searchable list for naming a cog. |
| `src/index.css` | The theme and the per-track colours. |
| `src/assets/` | Gag and cog pictures and three item icons, bundled into the build. |
| `dist/` | The built page the panels load. |
| `vite.config.js` | Sets `base: './'`. pywebview loads the page from `file://`, where absolute asset paths would not resolve. |

The page loads the Fredoka font from Google Fonts and falls back to a
system font when it cannot.

## Where the logic is

Not here. `Model` in `solver/live/overlay.py` and the shared worker in
`solver/live/worker.py` own every decision: whether a fight can be
confirmed, what the evidence line says, which engine's move leads. They
are free of both Tk and JavaScript, so they are tested without a display.
The page renders what it is sent.

`panel.model_json` is the whole payload, and
[docs/panel-contract.md](../docs/panel-contract.md) documents every field
and every method the page may call.

If the page needs something the model does not expose, add a property to
`Model`. A second implementation of a decision in JavaScript would drift
from the tested one.

## Rules the tests enforce

`tests/test_panel_bridge.py` reads the source files in `src/` and fails
when:

- a `call('name', ...)` names a method that `panel.Api` does not have, or
  passes the wrong number of arguments;
- the page reads a `model.<field>` that `model_json` does not send;
- `call` is declared inside a component, where other components cannot
  reach it.

It finds call sites with a regular expression that stops at the first
`)`, so keep the arguments of every `call(...)` flat: plain variables, no
nested function calls.

A method must exist on both `panel.Api` and `realms_panel.RealmsApi`,
because the page is shared. `tests/test_realms_panel.py` checks the
Realms side.

## Why a webview

The panel has to stay on top and sit against the game window, which rules
out a browser tab. A Tk version of the panel still exists
(`python -m solver.live.overlay`) for machines without a webview, but it
shows only one recommendation and the cog list.
