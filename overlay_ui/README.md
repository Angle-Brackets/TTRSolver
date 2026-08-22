# Overlay UI

React + Tailwind + daisyUI, rendered in a pywebview window by
`solver/live/panel.py`.

## Running it

    pip install pywebview
    python -m solver.live.panel

**No Node needed.** `dist/` is committed, so running the overlay needs a
build toolchain no more than running the solver needs a compiler.

## Changing it

    cd overlay_ui
    npm install
    npm run dev      # hot reload in a browser, no Python
    npm run build    # writes dist/, which must be committed

`npm run dev` is useful on its own: with no Python behind it the page
renders the empty model, and `window.pushModel({...})` from the console
drives any state you want to look at.

## Where the logic is

Not here. `overlay.Model` owns every decision -- whether a fight can be
confirmed, what the evidence line says, when advice goes stale -- and
stays free of both Tk and JS so it can be tested without a display.
`panel.model_json` is the whole interface.

If the page needs something the model does not expose, add a property to
`Model`. A second implementation of "may the player confirm a battle"
would drift, and the copy in the UI is the one nobody tests.

## Why a webview at all

The panel has to be always-on-top and parked against the game window,
which rules out a browser tab. Tk does that, and did it for a while, but
cannot draw a rounded card, a real progress bar or a button that does
not look like 1998.
