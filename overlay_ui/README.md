# TTRSolver Overlay UI

The lightweight React front-end displayed inside the live in-game HUD overlay window.

Styled with **Tailwind CSS** and **daisyUI**, this interface runs seamlessly inside a borderless, always-on-top desktop window powered by `pywebview` (using Microsoft Edge WebView2 on Windows).

```mermaid
flowchart LR
    subgraph PythonBackend["Python Backend"]
        Worker["AdviceWorker<br/>(Reads screen & runs AI)"]
        Bridge["pywebview JS Bridge"]
    end

    subgraph ReactFrontEnd["React Overlay (overlay_ui)"]
        Card["Recommended Move Card"]
        Engines["3 AI Engine Rows"]
        Cogs["Cog Health & Lure Rows"]
        Settings["Strategy & Party Settings"]
    end

    Worker -->|Pushes JSON Model| Bridge -->|window.pushModel()| ReactFrontEnd
    ReactFrontEnd -.->|User clicks button| Bridge -.->|call('method', args)| Worker
```

The overlay is shared across both supported game environments:
- **`solver/live/panel.py`**: The live overlay for **Toontown Rewritten (TTR)**.
- **`solver/live/realms_panel.py`**: The live overlay for **Toontown Realms**.

> [!NOTE]
> **Zero Node.js Required to Run:** The built React bundle is committed and pre-packaged in `overlay_ui/dist/`. Players only need Python to run the overlay!

---

## Table of Contents

- [Quick Start](#quick-start)
- [Developer Setup](#developer-setup)
- [Component Structure](#component-structure)
- [Logic Architecture](#logic-architecture)
- [Panel Bridge & Contract Rules](#panel-bridge--contract-rules)
- [Why a Webview Window?](#why-a-webview-window)

---

## Quick Start

To launch the live overlay alongside your game:

```bash
# 1. Install pywebview
pip install pywebview

# 2. Run the TTR overlay
python run.py 1
```

If `overlay_ui/dist/` is ever missing, the launcher will clearly instruct you how to build it rather than failing silently.

---

## Developer Setup

If you are developing or tweaking the look of the overlay:

```bash
cd overlay_ui

# 1. Install dependencies
npm install

# 2. Start local hot-reload dev server (no Python required!)
npm run dev

# 3. Build production bundle for Python
npm run build
```

### Standalone UI Prototyping (`npm run dev`)
When running `npm run dev` in your browser, no Python backend is connected. You can test any board state by opening your browser developer console (`F12`) and injecting a mock model state directly:

```javascript
window.pushModel({
  status: "IN BATTLE",
  lead_move: { track_name: "Throw", level: 6, gag_name: "Birthday Cake", acc: 0.95 },
  engines: [
    { name: "Playout", move_desc: "Birthday Cake", status: "agrees" },
    { name: "Search", move_desc: "Storm Cloud", status: "different" },
    { name: "PPO", move_desc: "Birthday Cake", status: "agrees" }
  ],
  cogs: [
    { name: "Glad Hander", level: 11, dept: "Bossbot", hp: 104, max_hp: 156, is_lured: true }
  ]
});
```

---

## Component Structure

```
overlay_ui/
├── src/
│   ├── App.jsx             # Main dashboard: header, recommendation card, engine rows, cog list
│   ├── CogPicker.jsx       # Searchable modal dropdown for naming unfamiliar cogs
│   ├── index.css           # Styling theme, track colors, and custom fonts
│   └── assets/             # Gag icons, cog portraits, and department emblems
├── dist/                   # Production build loaded by Python pywebview
└── vite.config.js          # Configures relative asset paths ('./') for local file:// loading
```

- **Google Fonts:** Loads the playful *Fredoka* font from Google Fonts and gracefully falls back to system rounded sans-serif fonts if offline.
- **Relative Pathing:** `vite.config.js` sets `base: './'` so assets resolve cleanly when loaded via `file://` inside `pywebview`.

---

## Logic Architecture

**The React UI is purely presentational.** 

All decision logic, calculation of damage, validation of battle states, and engine consensus live in Python (`solver/live/overlay.py` and `solver/live/worker.py`).

```
[ Python Worker ] ──(Generates Model JSON)──> [ React State (UI Renders) ]
[ User Clicks Button ] ──(pywebview API Call)──> [ Python Worker Handles Action ]
```

This ensures that the exact same tested business logic drives all front-ends (the React webview, the Tkinter fallback GUI, and the terminal advisor) without risking divergence.

---

## Panel Bridge & Contract Rules

The data contract between Python and React is enforced by automated unit tests (`tests/test_panel_bridge.py`):

1. **Flat API Calls:** All calls from JavaScript to Python must be flat: `call('method_name', arg1, arg2)` (no nested functions in arguments).
2. **Dual-Server Compatibility:** Every method called by the React UI must exist on both `panel.Api` (TTR) and `realms_panel.RealmsApi` (Realms).
3. **No Phantom Properties:** Any `model.<field>` rendered in React must be explicitly defined in Python's `model_json` contract.

*Complete reference:* **[docs/panel-contract.md](../docs/panel-contract.md)**.

---

## Why a Webview Window?

The live overlay needs to stay on top of the game, dock smoothly against the edge of the game window, and respond instantly without latency. A standard web browser tab cannot stay pinned over another full-screen game, making an embedded native webview window (`pywebview`) the ideal lightweight solution.
