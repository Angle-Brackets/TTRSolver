import React, { useEffect, useState } from 'react'
import CogPicker from './CogPicker'

// The model Python posts. Shape matches `panel.model_json`; this default
// is also what the page shows when opened in a browser with no Python
// behind it, so `npm run dev` is useful on its own.
const EMPTY = {
  in_battle: false, status: 'waiting', turn: 0,
  advice: '', track: null, gag_level: null, rows: [], problems: [],
  evidence: '', can_confirm: false, can_advise: false, thinking: false,
  allow_level_7: true, objective: 'balanced', budget: 15,
  lure_icon: '', map_icon: '',
  zone: '', neighborhood: '', district: '', invasion: '',
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

// Matches `search.objective.PRESETS`. Kept in the same order the
// help text lists them so the dropdown reads predictably.
const OBJECTIVES = ['balanced', 'conserve', 'glass cannon', 'speedrun',
                    'survive']

// MODULE SCOPE, deliberately. This lived inside App(), and `CogRow` is
// its own component -- so every button in a cog row threw
// "call is not defined" the moment it was clicked. The picker and the
// lure marker both did nothing for that reason, and nothing reached
// Python to be debugged, which is why fixing six real bugs behind it
// changed nothing.
//
// Spread rather than a fixed argument: passing `undefined` explicitly
// still sends pywebview a positional argument, and `ask_now()`,
// `toggle_fight()` and `close()` take none.
const call = (name, ...args) => {
  if (window.pywebview?.api?.[name]) window.pywebview.api[name](...args)
}

function healthClass(h) {
  if (h > 0.6) return 'bg-success'
  if (h > 0.25) return 'bg-warning'
  return 'bg-error'
}

function CogRow({ row, lureIcon }) {
  const art = cogArt(row.art, row.department)
  return (
    <div className="flex items-start gap-2.5 py-[3px]">
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
      {/* Nothing reads the game's lure indicator, and an unlured
          assumption is wrong four ways at once: Throw and Squirt are
          forced to 100% with knockback, Drop always misses, and the cog
          does not attack. Until the plate is read, the player marks it. */}
      <button
        className={`flex shrink-0 items-center rounded px-[3px] py-[2px] text-[9px] font-semibold uppercase leading-none tracking-wide ${
          row.lured ? 'bg-warning/25 text-warning'
                    : 'opacity-20 grayscale hover:opacity-60'
        }`}
        onClick={() => call('mark_lured', row.index, !row.lured)}
        title={row.lured
          ? 'Asleep on a Lure: Throw and Squirt hit for certain with knockback, Drop misses, and it will not attack. Click if it is actually awake.'
          : 'Not lured. Click to mark it asleep if the reader missed the indicator.'}
      >
        {lureIcon
          ? <img src={lureIcon} alt="lured" className="size-[15px] object-contain" />
          : (row.lured ? 'LURED' : 'lure?')}
      </button>
      <CogPicker
        row={row}
        onPick={(key) => call('name_cog', row.index, key)}
      />
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
  // panel grows and shrinks with the number of cogs, the length of the
  // evidence line, and whether a cog picker is open.
  //
  // A ResizeObserver, NOT an effect on [model]. Opening the picker
  // changes the layout without changing the model, so a model-keyed
  // effect never fired and the window stayed short -- leaving the open
  // list past its bottom edge, drawn over the game and impossible to
  // click. Watching the element itself catches every cause.
  //
  // MEASURE #panel, NOT #root. index.css gives html/body/#root
  // `height: 100%`, so #root.scrollHeight can never fall below the
  // current viewport and the window would only ever grow.
  useEffect(() => {
    const panel = document.getElementById('panel')
    if (!panel) return undefined
    const send = () => {
      const h = panel.scrollHeight
      if (h && window.pywebview?.api?.set_height) {
        window.pywebview.api.set_height(Math.ceil(h))
      }
    }
    send()
    if (typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(send)
    ro.observe(panel)
    return () => ro.disconnect()
  }, [])

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
      </div>

      {/* Live controls. Every value comes from the model, never from
          local state, so a control shows what the solver is actually
          doing rather than what the page last asked for. */}
      <div className="flex items-center gap-1.5 text-[11px]">
        <select
          className="select select-xs h-[22px] min-h-0 w-[7.5rem] bg-base-200 text-[11px]"
          value={model.objective}
          onChange={(e) => call('set_objective', e.target.value)}
          title="How to play: balanced, conserve gags, all-out, fastest, safest"
        >
          {OBJECTIVES.map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>

        <div className="flex items-center gap-1 opacity-70">
          <span className="opacity-60">think</span>
          <input
            type="range" min="3" max="45" step="1"
            className="range range-xs w-[5.5rem]"
            value={model.budget}
            onChange={(e) => call('set_budget', Number(e.target.value))}
          />
          <span className="w-7 font-mono tabular-nums">{Math.round(model.budget)}s</span>
        </div>

        <button
          className={`btn btn-xs ml-auto h-[22px] min-h-0 px-2 text-[10px] font-semibold tracking-wide ${
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
        {model.in_battle && model.rows.length > 0
          ? model.rows.slice(0, 4).map((row, i) => (
              <CogRow key={i} row={row} lureIcon={model.lure_icon} />
            ))
          : null}
        {/* ALWAYS SHOWN when there are any. These used to render only
            when NOT in a battle, so an in-battle refusal -- an
            unidentified cog, a gag-count checksum that does not add up --
            produced "no move to recommend" with the reason hidden. The
            reason is the most useful thing on the panel at that moment,
            because every one of them is something the player can fix. */}
        {model.problems.length > 0 && (
          <div className={`space-y-[2px] text-[12px] ${
            model.in_battle ? 'pt-2 text-warning opacity-90' : 'pt-1 opacity-50'
          }`}>
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

      <div className="flex items-end justify-between gap-2">
        <div
          className={`text-[11px] ${
            model.can_confirm ? 'opacity-35' : 'text-warning opacity-80'
          }`}
        >
          {model.evidence}
        </div>

        {/* Where the toon is, from the Local API. The solver never uses
            it -- a street does not change a round. It is here because it
            is the only thing on the panel that proves the API is
            connected: the cog readers work off pixels and would look
            exactly the same with it down. */}
        {model.zone && (
          <div
            className="flex shrink-0 items-center gap-1 text-[10px] opacity-40"
            title={`${model.zone}, ${model.neighborhood} — district ${model.district}`}
          >
            {model.map_icon && (
              <img src={model.map_icon} alt="" className="size-[13px] object-contain" />
            )}
            <span className="max-w-[9rem] truncate">{model.zone}</span>
          </div>
        )}
      </div>

      {/* An invasion changes which cogs walk in, so it is worth saying
          out loud rather than hiding in a tooltip. */}
      {model.invasion && (
        <div className="flex items-center gap-1 text-[11px] text-warning opacity-90">
          <span className="font-semibold uppercase tracking-wide">invasion</span>
          <span className="truncate opacity-80">{model.invasion}</span>
        </div>
      )}
    </div>
  )
}
