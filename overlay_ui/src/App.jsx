import React, { useEffect, useState } from 'react'

// The model Python posts. Shape matches `panel.model_json`; this default
// is also what the page shows when opened in a browser with no Python
// behind it, so `npm run dev` is useful on its own.
const EMPTY = {
  in_battle: false, status: 'waiting', turn: 0,
  advice: '', track: null, gag_level: null, rows: [], problems: [],
  evidence: '', can_confirm: false, can_advise: false, thinking: false,
  allow_level_7: true,
}

// THE REAL GAME ART, not a generic icon set. Vite fingerprints and
// bundles whatever these globs match, so the lookups below are plain
// string keys with no runtime fetch -- which matters, because the panel
// has no network and sits over a game that may be fullscreen.
//
// Gag files are `gag-<track>-<level>.png` and the track slugs are
// `Track.value` verbatim (toon_up, trap, lure, sound, throw, squirt,
// drop), so `model.track` and `model.gag_level` index them directly.
const GAG_ART = import.meta.glob('./assets/gags/*.png', {
  eager: true, import: 'default',
})
const COG_ART = import.meta.glob('./assets/cogs/*.png', {
  eager: true, import: 'default',
})

const gagArt = (track, level) =>
  (track && level) ? GAG_ART[`./assets/gags/gag-${track}-${level}.png`] : null

// Falls back to the department emblem, which is the honest picture when
// a plate was read to a department but not to a single cog. Drawing a
// specific cog there would assert more than was actually read.
const cogArt = (art, department) =>
  (art && COG_ART[`./assets/cogs/cog-${art}.png`]) ||
  (department && COG_ART[`./assets/cogs/dept-${department}.png`]) ||
  null

function healthClass(h) {
  if (h > 0.6) return 'bg-success'
  if (h > 0.25) return 'bg-warning'
  return 'bg-error'
}

function CogRow({ row }) {
  const art = cogArt(row.art, row.department)
  return (
    <div className="flex items-center gap-2.5 py-[3px]">
      <div className="size-7 shrink-0 overflow-hidden rounded-full bg-base-300 ring-1 ring-white/5">
        {art ? (
          <img
            src={art}
            alt=""
            className={`size-full object-cover ${
              row.identified ? '' : 'opacity-45 saturate-50'
            }`}
          />
        ) : null}
      </div>
      <span className="w-5 shrink-0 text-right font-mono text-[11px] opacity-40">
        {row.level ?? '?'}
      </span>
      <span
        className={`w-28 shrink-0 truncate text-[13px] ${
          row.identified ? 'opacity-80' : 'opacity-40 italic'
        }`}
      >
        {row.name}
      </span>
      <div className="h-[6px] flex-1 overflow-hidden rounded-full bg-base-300">
        <div
          className={`h-full rounded-full transition-[width] duration-300 ${healthClass(
            row.health,
          )}`}
          style={{ width: `${Math.max(3, row.health * 100)}%` }}
        />
      </div>
      <span className="w-9 shrink-0 text-right font-mono text-[11px] opacity-60">
        {Math.round(row.health * 100)}%
      </span>
    </div>
  )
}

function Advice({ model }) {
  const showing = Boolean(model.advice) && model.in_battle
  const track = showing && model.track ? model.track : 'none'
  const art = showing ? gagArt(model.track, model.gag_level) : null
  return (
    <div
      className={`track-${track} relative flex items-center gap-3 overflow-hidden rounded-box bg-base-200 px-4 py-3`}
    >
      <div
        className="absolute inset-y-0 left-0 w-[3px]"
        style={{ background: 'var(--accent)' }}
      />
      {art && (
        <img
          src={art}
          alt=""
          className="size-11 shrink-0 object-contain drop-shadow"
        />
      )}
      <div className="min-w-0">
        {showing && model.track && (
          <div
            className="text-[10px] font-semibold tracking-[0.14em]"
            style={{ color: 'var(--accent)' }}
          >
            {model.track.replace('_', '-').toUpperCase()}
            {model.gag_level ? ` · ${model.gag_level}` : ''}
          </div>
        )}
        <div
          className={
            showing
              ? 'text-[17px] font-bold leading-tight'
              : 'text-[14px] opacity-50'
          }
        >
          {model.thinking && !showing ? (
            <span className="inline-flex items-center gap-2">
              <span className="loading loading-dots loading-sm" />
              thinking
            </span>
          ) : (
            model.advice || (model.in_battle
              ? 'no move to recommend'
              : 'waiting for a battle')
          )}
        </div>
      </div>
    </div>
  )
}

export default function App() {
  const [model, setModel] = useState(EMPTY)

  useEffect(() => {
    // Python pushes by calling window.pushModel; polling is the fallback
    // for `npm run dev`, where there is no Python at all.
    window.pushModel = (next) => setModel({ ...EMPTY, ...next })
    return () => { delete window.pushModel }
  }, [])

  // Report the content height so Python can size the window to it. The
  // panel grows and shrinks with the number of cogs and the length of
  // the evidence line, and a fixed height either clips or leaves a dead
  // strip -- which is the bug the Tk version had.
  //
  // MEASURE #panel, NOT #root. index.css gives html/body/#root
  // `height: 100%` so the background fills the window, which also means
  // #root.scrollHeight can never drop below the current viewport -- ask
  // it and the window only ever grows. Two cogs left in a fight sat in a
  // window sized for four, which is the same dead strip in a new place.
  useEffect(() => {
    const send = () => {
      const h = document.getElementById('panel')?.scrollHeight
      if (h && window.pywebview?.api?.set_height) {
        window.pywebview.api.set_height(Math.ceil(h))
      }
    }
    const id = requestAnimationFrame(send)
    return () => cancelAnimationFrame(id)
  }, [model])

  // Spread, not a fixed `arg`. Passing `undefined` explicitly still
  // sends pywebview a positional argument, and `ask_now()` /
  // `toggle_fight()` / `close()` take none -- which crashed the bridge
  // with "takes 1 positional argument but 2 were given".
  const call = (name, ...args) => {
    if (window.pywebview?.api?.[name]) window.pywebview.api[name](...args)
  }

  return (
    <div id="panel" className="flex flex-col gap-2 bg-base-100 p-4 text-base-content">
      <div className="flex items-center gap-2">
        <span
          className={`inline-block size-[7px] rounded-full ${
            model.in_battle ? 'bg-success' : 'bg-base-300'
          }`}
        />
        <span
          className={`text-[11px] font-semibold tracking-[0.12em] ${
            model.in_battle ? 'text-success' : 'opacity-50'
          }`}
        >
          {model.status.toUpperCase()}
        </span>
        <span className="ml-auto text-[11px] opacity-35">
          {model.turn ? `turn ~${model.turn}` : ''}
        </span>
        {/* Holding 7s back is a real decision mid-run -- you save them
            for the boss -- so it is a toggle rather than only a launch
            flag. The value comes from the model, not from local state,
            so the button shows what the solver is actually doing. */}
        <button
          className={`btn btn-xs h-[20px] min-h-0 px-2 text-[10px] font-semibold tracking-wide ${
            model.allow_level_7 ? 'btn-ghost opacity-45' : 'btn-warning'
          }`}
          onClick={() => call('set_level_7', !model.allow_level_7)}
          title={model.allow_level_7
            ? 'Level 7 gags are being offered — click to hold them back'
            : 'Level 7 gags are held back — click to allow them'}
        >
          {model.allow_level_7 ? '7s ON' : '7s HELD'}
        </button>
      </div>

      <Advice model={model} />

      <div className="min-h-[10px]">
        {model.in_battle && model.rows.length > 0 ? (
          model.rows.slice(0, 4).map((row, i) => <CogRow key={i} row={row} />)
        ) : (
          <div className="space-y-[2px] pt-1 text-[12px] opacity-50">
            {model.problems.slice(0, 4).map((line, i) => (
              <div key={i}>{line}</div>
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center gap-2 pt-1">
        <button
          className="btn btn-sm btn-ghost text-[12px] font-normal"
          disabled={!model.can_confirm}
          onClick={() => call('toggle_fight')}
        >
          {model.in_battle ? 'Fight is over' : "I'm in a fight"}
        </button>
        <button
          className="btn btn-sm btn-primary text-[12px]"
          disabled={!model.can_advise}
          onClick={() => call('ask_now')}
        >
          {model.thinking ? 'thinking…' : 'Work it out'}
        </button>
        <button
          className="btn btn-sm btn-ghost btn-square ml-auto opacity-40"
          onClick={() => call('close')}
          title="close"
        >
          &#10005;
        </button>
      </div>

      <div
        className={`text-[11px] ${
          model.can_confirm ? 'opacity-35' : 'text-warning opacity-80'
        }`}
      >
        {model.evidence}
      </div>
    </div>
  )
}
