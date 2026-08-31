import React, { useEffect, useState } from 'react'
import CogPicker from './CogPicker'

// The model Python posts. Shape matches `panel.model_json`; this default
// is also what the page shows when opened in a browser with no Python
// behind it, so `npm run dev` is useful on its own.
const EMPTY = {
  in_battle: false, status: 'waiting', turn: 0,
  advice: '', track: null, gag_level: null, rows: [], problems: [],
  evidence: '', can_confirm: false, can_advise: false, thinking: false,
  allow_level_7: true, objective: 'balanced', budget: 15, toon_count: 1,
  engine: '',
  // The badge reads both: `engine` labels what is on screen,
  // `preferred_engine` and `search_ready` decide whether to show the
  // waiting ellipsis.
  preferred_engine: 'rl', search_ready: false,
  max_fires: 0, max_unites: 0, max_sos: 0, unite: '',
  lure_icon: '', map_icon: '',
  zone: '', neighborhood: '', district: '', invasion: '',
}

// THE REAL GAME ART, not a generic icon set. Vite fingerprints and
// bundles whatever these globs match, so the lookups below are plain
// string keys with no runtime fetch -- which matters, because the panel
// has no network and sits over a game that may be fullscreen.
const GAG_ART = import.meta.glob('./assets/gags/*.png', {
  eager: true, import: 'default',
})
const COG_ART = import.meta.glob('./assets/cogs/*.png', {
  eager: true, import: 'default',
})

const gagArt = (track, level) =>
  (track && level) ? GAG_ART[`./assets/gags/gag-${track}-${level}.png`] : null

import pinkSlipArt from './assets/pink-slip.png'
import sosCardArt from './assets/sos-card.png'
import uniteFistArt from './assets/unite-fist.png'

const PinkSlip = ({ size = 'size-11' }) => (
  <img src={pinkSlipArt} alt="" className={`${size} object-contain`} />
)

const SosCard = ({ size = 'size-11' }) => (
  <img src={sosCardArt} alt="" className={`${size} object-contain`} />
)

const UniteFist = ({ size = 'size-4' }) => (
  <img src={uniteFistArt} alt="" className={`${size} shrink-0 object-contain`} />
)

const cogArt = (art, department) =>
  (art && COG_ART[`./assets/cogs/cog-${art}.png`]) ||
  (department && COG_ART[`./assets/cogs/dept-${department}.png`]) ||
  null

const OBJECTIVES = ['balanced', 'conserve', 'glass cannon', 'speedrun', 'survive']

// MODULE SCOPE helper for pywebview API calls
const call = (name, ...args) => {
  if (window.pywebview?.api?.[name]) window.pywebview.api[name](...args)
}

function healthClass(h) {
  if (h > 0.6) return 'bg-success'
  if (h > 0.25) return 'bg-warning'
  return 'bg-error'
}

// Determines if a cog row is targeted by the current advice text
function isCogTargeted(row, advice, inBattle) {
  if (!inBattle || !advice) return false
  const lowerAdvice = advice.toLowerCase()
  const cogIndexTag = `cog ${row.index + 1}`
  if (lowerAdvice.includes(cogIndexTag)) return true
  if (lowerAdvice.includes('on all cogs')) return true
  if (row.name && row.name !== 'Unknown' && lowerAdvice.includes(row.name.toLowerCase())) return true
  return false
}

function CogRow({ row, lureIcon, advice, inBattle }) {
  const targeted = isCogTargeted(row, advice, inBattle)
  const art = cogArt(row.art, row.department)
  const magnetArt = lureIcon || gagArt('lure', 5)

  return (
    <div
      className={`relative flex items-center gap-2 rounded-lg px-2 py-1 transition-all duration-200 ${
        targeted
          ? 'cog-target-highlight border border-amber-400/80 bg-amber-500/15 shadow-lg shadow-amber-500/20'
          : 'bg-base-200/40 border border-white/5 hover:bg-base-200/80'
      }`}
    >
      <div className="relative size-7 shrink-0 overflow-hidden rounded-full bg-base-300 ring-1 ring-white/10">
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

      <span className="w-4 shrink-0 text-right font-mono text-[11px] font-bold opacity-75">
        {row.level ?? '?'}
      </span>

      {/* TARGET BADGE */}
      {targeted && (
        <span className="flex items-center gap-0.5 rounded bg-amber-400/25 px-1 py-0.5 text-[8px] font-black uppercase tracking-wider text-amber-300 ring-1 ring-amber-400/50 shadow-sm shrink-0">
          <span className="text-[9px]">🎯</span> TARGET
        </span>
      )}

      {/* LURED STATUS MAGNET BADGE */}
      <button
        type="button"
        className={`flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[9px] font-extrabold uppercase tracking-wide transition-all duration-200 ${
          row.lured
            ? 'border border-emerald-500 bg-emerald-500/20 text-emerald-300 shadow-[0_0_8px_rgba(16,185,129,0.3)]'
            : 'border border-rose-500/60 bg-rose-500/10 text-rose-300 opacity-70 hover:opacity-100 hover:border-rose-400'
        }`}
        onClick={() => call('mark_lured', row.index, !row.lured)}
        title={
          row.lured
            ? 'LURED (Asleep): Throw & Squirt hit with knockback bonus; Drop misses. Click if awake.'
            : 'UNLURED (Awake): Cog can attack. Click to mark asleep.'
        }
      >
        {magnetArt ? (
          <img
            src={magnetArt}
            alt=""
            className={`size-[13px] object-contain ${row.lured ? '' : 'grayscale opacity-70'}`}
          />
        ) : (
          <span>🧲</span>
        )}
        <span>{row.lured ? 'LURED' : 'AWAKE'}</span>
      </button>

      <CogPicker
        row={row}
        onPick={(key) => call('name_cog', row.index, key)}
      />

      <div className="h-[6px] flex-1 min-w-[2rem] overflow-hidden rounded-full bg-base-300/80">
        <div
          className={`h-full rounded-full transition-[width] duration-300 ${healthClass(
            row.health,
          )}`}
          style={{ width: `${Math.max(3, row.health * 100)}%` }}
        />
      </div>

      <span className="w-8 shrink-0 text-right font-mono text-[10px] font-bold tabular-nums opacity-75">
        {Math.round(row.health * 100)}%
      </span>
    </div>
  )
}

function Advice({ model }) {
  const showing = Boolean(model.advice) && model.in_battle
  const track = showing && model.track ? model.track : 'none'
  const firing = showing && model.track === 'fire'
  const calling = showing && model.track === 'sos'
  const art = showing && !firing && !calling
    ? gagArt(model.track, model.gag_level) : null

  return (
    <div className="space-y-1.5">
      {/* 0-TURN INSTANT UNITE BANNER */}
      {showing && model.unite && (
        <div className="flex items-center gap-2 rounded-lg border border-emerald-500/50 bg-gradient-to-r from-emerald-950/40 via-base-200 to-base-200 px-3 py-1.5 text-emerald-300 shadow-[0_0_12px_rgba(16,185,129,0.2)] animate-pulse">
          <div className="flex size-6 shrink-0 items-center justify-center rounded-full bg-emerald-500/20 ring-1 ring-emerald-400/50">
            <UniteFist size="size-3.5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[8px] font-black tracking-widest uppercase text-emerald-400">
              USE UNITE FIRST (0-TURN INSTANT)
            </div>
            <div className="text-[11px] font-bold tracking-wide text-emerald-200 truncate">
              {model.unite}
            </div>
          </div>
        </div>
      )}

      {/* MAIN HERO ACTION CARD */}
      <div className={`track-${track} card-track-glow relative flex items-center gap-3 overflow-hidden rounded-xl bg-base-200 p-3 border border-white/10 shadow-md`}>
        {art && (
          <div className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-base-300/80 p-1 ring-1 ring-white/10 shadow-inner">
            <img src={art} alt="" className="size-full object-contain drop-shadow" />
          </div>
        )}

        {firing && (
          <div className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-pink-500/20 ring-1 ring-pink-400/40 shadow-md shadow-pink-500/20">
            <PinkSlip size="size-9" />
          </div>
        )}

        {calling && (
          <div className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-amber-500/20 ring-1 ring-amber-400/40 shadow-md shadow-amber-500/20">
            <SosCard size="size-9" />
          </div>
        )}

        <div className="min-w-0 flex-1">
          {showing && model.track && (
            <div className="flex items-center gap-1.5">
              <span
                className="text-[10px] font-black tracking-widest uppercase"
                style={{ color: 'var(--accent)' }}
              >
                {firing ? '🔥 PINK SLIP · FIRE'
                  : calling ? '⭐ SOS CALL'
                  : model.track.replace('_', '-').toUpperCase()}
              </span>
              {model.gag_level && !firing && !calling && (
                <span className="rounded-full bg-base-300 px-1.5 py-0.2 text-[9px] font-bold text-base-content/80 ring-1 ring-white/10">
                  LVL {model.gag_level}
                </span>
              )}
            </div>
          )}

          <div
            className={
              showing
                ? 'text-[15px] font-black leading-snug tracking-tight text-base-content'
                : 'text-[13px] font-medium opacity-60'
            }
          >
            {model.thinking && !showing ? (
              <span className="inline-flex items-center gap-1.5 text-primary font-semibold">
                <span className="loading loading-dots loading-xs" />
                computing best strategy...
              </span>
            ) : (
              model.advice || (model.in_battle
                ? 'no move to recommend'
                : 'waiting for a battle')
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function StepperControl({ label, icon, value, onChange, title }) {
  return (
    <div
      className="flex flex-1 min-w-0 items-center justify-between gap-1 rounded-lg border border-white/10 bg-base-200/90 px-1.5 py-1 shadow-sm"
      title={title}
    >
      <div className="flex items-center gap-1 min-w-0 shrink">
        {icon}
        <span className="text-[9px] font-extrabold uppercase tracking-wide opacity-80 truncate">
          {label}
        </span>
      </div>
      <div className="flex items-center gap-0.5 shrink-0">
        <button
          type="button"
          className="flex size-4.5 items-center justify-center rounded bg-base-300 text-[11px] font-bold opacity-80 hover:bg-primary hover:text-primary-content hover:opacity-100 disabled:opacity-20"
          disabled={value <= 0}
          onClick={() => onChange(Math.max(0, value - 1))}
        >
          -
        </button>
        <span className="w-4 text-center font-mono text-[10px] font-bold tabular-nums">
          {value}
        </span>
        <button
          type="button"
          className="flex size-4.5 items-center justify-center rounded bg-base-300 text-[11px] font-bold opacity-80 hover:bg-primary hover:text-primary-content hover:opacity-100"
          onClick={() => onChange(value + 1)}
        >
          +
        </button>
      </div>
    </div>
  )
}

export default function App() {
  const [model, setModel] = useState(EMPTY)

  useEffect(() => {
    window.pushModel = (next) => setModel({ ...EMPTY, ...next })
    return () => { delete window.pushModel }
  }, [])

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
    <div id="panel" className="flex flex-col gap-2 bg-base-100 p-3 text-base-content select-none">
      {/* HEADER BAR WITH TOP-RIGHT CLOSE BUTTON */}
      <div className="flex items-center gap-2 rounded-lg bg-base-200/60 px-2.5 py-1 border border-white/5">
        <span
          className={`inline-block size-2 rounded-full ${
            model.in_battle ? 'bg-success shadow-[0_0_8px_rgba(34,197,94,0.6)] animate-pulse' : 'bg-base-300'
          }`}
        />
        <span
          className={`text-[10px] font-extrabold tracking-wider uppercase ${
            model.in_battle ? 'text-success' : 'opacity-50'
          }`}
        >
          {model.status.toUpperCase()}
        </span>

        {model.engine && (
          <button
            type="button"
            onClick={() => call('prefer_engine', model.engine === 'rl' ? 'search' : 'rl')}
            className={`badge badge-xs h-[16px] px-1.5 text-[8px] font-black tracking-widest cursor-pointer hover:scale-105 transition-transform ${
              model.engine === 'rl' ? 'badge-ghost opacity-70' : 'badge-primary'
            }`}
            title={
              model.engine === 'rl'
                ? 'Trained policy — instant response. Click for expectimax search.'
                : 'Expectimax search — honours objective. Click for policy answer.'
            }
          >
            {model.engine === 'rl' ? 'RL' : 'SEARCH'}
            {model.preferred_engine === 'search' && !model.search_ready ? '…' : ''}
          </button>
        )}

        <span className="ml-auto font-mono text-[10px] font-bold opacity-50">
          {model.turn ? `turn ~${model.turn}` : ''}
        </span>

        {/* TOP RIGHT CLOSE BUTTON */}
        <button
          type="button"
          className="flex size-5 items-center justify-center rounded text-[11px] opacity-40 hover:bg-white/10 hover:opacity-100"
          onClick={() => call('close')}
          title="Close overlay"
        >
          ✕
        </button>
      </div>

      {/* STRATEGY CONTROLS BAR */}
      <div className="flex flex-wrap items-center gap-1.5 rounded-lg bg-base-200/40 p-1.5 border border-white/5 text-[10px]">
        {/* OBJECTIVE SELECT */}
        <select
          className="select select-xs h-[22px] min-h-0 w-[6.5rem] bg-base-200 font-medium text-[10px] border border-white/10 rounded"
          value={model.objective}
          onChange={(e) => call('set_objective', e.target.value)}
          title="Strategy Objective: balanced, conserve, glass cannon, speedrun, survive"
        >
          {OBJECTIVES.map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>

        {/* BUDGET RANGE SLIDER */}
        <div className="flex items-center gap-1 opacity-80" title="Max thinking time per search (seconds)">
          <span className="text-[9px] font-bold uppercase opacity-60">think</span>
          <input
            type="range" min="3" max="45" step="1"
            className="range range-xs range-primary w-[3.5rem]"
            value={model.budget}
            onChange={(e) => call('set_budget', Number(e.target.value))}
          />
          <span className="w-5 font-mono text-[9px] font-bold tabular-nums opacity-90">{Math.round(model.budget)}s</span>
        </div>

        {/* TOONS COUNT */}
        <div
          className="flex items-center gap-1 ml-auto"
          title="Party size counting you (1-4 toons)."
        >
          <span className="text-[9px] font-bold uppercase opacity-50">toons</span>
          <div className="join">
            {[1, 2, 3, 4].map((n) => (
              <button
                key={n}
                type="button"
                className={`btn btn-xs join-item h-[20px] min-h-0 w-[18px] px-0 text-[9px] font-black ${
                  model.toon_count === n ? 'btn-primary' : 'btn-ghost opacity-40'
                }`}
                onClick={() => call('set_toon_count', n)}
              >
                {n}
              </button>
            ))}
          </div>
        </div>

        {/* LEVEL 7 TOGGLE */}
        <button
          type="button"
          className={`btn btn-xs h-[20px] min-h-0 px-1.5 text-[9px] font-black tracking-wide ${
            model.allow_level_7 ? 'btn-ghost opacity-60' : 'btn-warning shadow-md'
          }`}
          onClick={() => call('set_level_7', !model.allow_level_7)}
          title={
            model.allow_level_7
              ? 'Level 7 gags allowed. Click to hold them back.'
              : 'Level 7 gags held back for boss. Click to allow.'
          }
        >
          {model.allow_level_7 ? '7s ON' : '7s HELD'}
        </button>
      </div>

      {/* ADVICE HERO */}
      <Advice model={model} />

      {/* COG ROSTER */}
      <div className="min-h-[10px] space-y-1">
        {model.in_battle && model.rows.length > 0
          ? model.rows.slice(0, 4).map((row, i) => (
              <CogRow
                key={i}
                row={row}
                lureIcon={model.lure_icon}
                advice={model.advice}
                inBattle={model.in_battle}
              />
            ))
          : null}

        {model.problems.length > 0 && (
          <div className={`space-y-0.5 text-[10px] font-medium ${
            model.in_battle ? 'pt-1 text-warning opacity-90' : 'pt-0.5 opacity-60'
          }`}>
            {model.problems.slice(0, 4).map((line, i) => (
              <div key={i} className="flex items-center gap-1">
                <span>⚠️</span> <span>{line}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* CONSUMABLE STEPPER CONTROLS (COMPACT 3 COLUMNS) */}
      <div className="flex items-center gap-1.5">
        <StepperControl
          label="SLIPS"
          icon={<PinkSlip size="size-3.5" />}
          value={model.max_fires}
          onChange={(val) => call('set_max_fires', val)}
          title="Max Pink Slips (Fires) allowed (0 = never fire)"
        />
        <StepperControl
          label="UNITES"
          icon={<UniteFist size="size-3.5" />}
          value={model.max_unites}
          onChange={(val) => call('set_max_unites', val)}
          title="Max Unites allowed (0 = never unite)"
        />
        <StepperControl
          label="SOS"
          icon={<SosCard size="size-3.5" />}
          value={model.max_sos}
          onChange={(val) => call('set_max_sos', val)}
          title="Max SOS cards allowed (0 = never use SOS)"
        />
      </div>

      {/* BOTTOM CONTROL ACTIONS */}
      <div className="flex items-center gap-2 pt-0.5 border-t border-white/5">
        <button
          type="button"
          className="btn btn-xs h-[24px] min-h-0 btn-ghost text-[10px] font-bold opacity-80 hover:opacity-100"
          disabled={!model.can_confirm}
          onClick={() => call('toggle_fight')}
        >
          {model.in_battle ? 'Fight is over' : "I'm in a fight"}
        </button>

        <button
          type="button"
          className="btn btn-xs h-[24px] min-h-0 btn-primary text-[10px] font-bold shadow"
          disabled={!model.can_advise || !model.advice}
          onClick={() => call('reconsider')}
          title="Reject this suggestion and show the next best move for this board"
        >
          Reconsider
        </button>
      </div>

      {/* FOOTER METADATA */}
      <div className="flex items-end justify-between gap-2 text-[9.5px] opacity-50 font-medium">
        <div className={model.can_confirm ? '' : 'text-warning opacity-90'}>
          {model.evidence}
        </div>

        {model.zone && (
          <div
            className="flex shrink-0 items-center gap-1"
            title={`${model.zone}, ${model.neighborhood} — district ${model.district}`}
          >
            {model.map_icon && (
              <img src={model.map_icon} alt="" className="size-3 object-contain" />
            )}
            <span className="max-w-[8rem] truncate">{model.zone}</span>
          </div>
        )}
      </div>

      {model.invasion && (
        <div className="flex items-center gap-1 text-[9.5px] font-bold text-warning opacity-90">
          <span className="uppercase tracking-wider">INVASION:</span>
          <span className="truncate opacity-80">{model.invasion}</span>
        </div>
      )}
    </div>
  )
}
