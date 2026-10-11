import React, { useEffect, useState } from 'react'
import CogPicker from './CogPicker'

const EMPTY = {
  in_battle: false, status: 'waiting', turn: 0,
  advice: '', track: null, gag_level: null, rows: [], problems: [],
  evidence: '', can_confirm: false, can_advise: false, thinking: false,
  allow_level_7: true, objective: 'balanced', budget: 15, toon_count: 1,
  engine: '', preferred_engine: 'rl', search_ready: false,
  max_fires: 0, max_unites: 0, max_sos: 0, unite: '',
  incoming: null, survive: null, accuracy: null, reason: '', organic: false, organic_tracks: [], organic_icon: '',
  rl_gag: '', rl_track: '', rl_gag_level: 0, rl_accuracy: null, rl_reason: '', rl_organic: false,
  search_gag: '', search_track: '', search_gag_level: 0, search_accuracy: null, search_reason: '', search_organic: false,
  playout_gag: '', playout_track: '', playout_gag_level: 0, playout_ready: false, playout_note: '', playout_rollouts: 0, playout_done: false, playout_pending: false,
  playout_accuracy: null, playout_reason: '', playout_organic: false, engines: ['rl', 'search', 'playout'],
  zone: '', neighborhood: '', district: '', invasion: '',
  lure_icon: '', map_icon: '', track_icons: {},
  feedback_move: '', feedback_against: '', feedback_problem: '',
  feedback_fixable: false, feedback_needs_target: false, feedback_showing: false,
  feedback_stated: false, pouch: [],
  boss_kind: '', boss_manual: '', cogs_defeated: 0, discord_floors: '', cogs_left: -1,
}

const BOSSES = [
  ['', 'None'], ['vp', 'VP'], ['cfo', 'CFO'], ['cj', 'CJ'], ['ceo', 'CEO'],
]

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

const PinkSlip = ({ size = 'size-4.5' }) => (
  <img src={pinkSlipArt} alt="" className={`${size} shrink-0 object-contain`} />
)

const SosCard = ({ size = 'size-4.5' }) => (
  <img src={sosCardArt} alt="" className={`${size} shrink-0 object-contain`} />
)

const UniteFist = ({ size = 'size-4.5' }) => (
  <img src={uniteFistArt} alt="" className={`${size} shrink-0 object-contain`} />
)

const OrganicLeaf = ({ icon, size = 'size-3.5' }) => (
  icon ? (
    <img src={icon} alt="Organic" title="Organic Gag (Extra damage / hit chance)" className={`${size} object-contain inline-block shrink-0`} />
  ) : (
    <span className="rounded bg-emerald-100 text-emerald-950 border border-emerald-300 px-1 py-0.2 text-[8px] font-black uppercase tracking-wider shrink-0 inline-flex items-center gap-0.5 shadow-2xs">
      🍃 ORG
    </span>
  )
)

const cogArt = (art, department) =>
  (art && COG_ART[`./assets/cogs/cog-${art}.png`]) ||
  (department && COG_ART[`./assets/cogs/dept-${department}.png`]) ||
  null

const OBJECTIVES = ['balanced', 'conserve', 'glass cannon', 'speedrun', 'survive']

const call = (name, ...args) => {
  if (window.pywebview?.api?.[name]) window.pywebview.api[name](...args)
}

// "I'D USE THIS INSTEAD" -- the positive channel.
//
// The pouch diff can only report what HAPPENED, and what happened is
// not always what the player endorses: following the advice to see how
// it plays records agreement, a misclick records a preference nobody
// holds, and a round that could not be read records nothing. This is
// where they say it outright.
//
// It offers ONLY what the toon is carrying. A preference for a move
// that was never available is not a preference, and the full
// seven-by-seven grid is unusable in a strip this size anyway.
function SuggestPicker({ model, onDone }) {
  const [track, setTrack] = useState(null)     // a track name, or null
  const [aiming, setAiming] = useState(null)   // a chosen move awaiting a cog

  const pouch = model.pouch || []
  const cogs = model.rows || []
  const tracks = []
  for (const row of pouch) if (!tracks.includes(row.track)) tracks.push(row.track)

  const send = (move, target) => {
    // Flattened deliberately: `test_panel_bridge` parses these call
    // sites to check they match the Python Api, and its reader stops at
    // the first ")" -- so a nested call here reads as a short argument
    // list and the arity check silently compares the wrong number.
    const isFire = move.fire === true
    const isPass = move.pass === true
    const track = move.track ?? null
    const level = move.level ?? null
    const at = target ?? null
    call('suggest_move', track, level, at, isFire, isPass)
    onDone()
  }

  // Ask for a cog only when there is a choice to make: a group gag has
  // no single target, and a one-cog board has only one answer.
  const choose = (move) => {
    if (move.pass) return send(move, null)
    if (move.group) return send(move, null)
    if (cogs.length <= 1) return send(move, 0)
    setAiming(move)
  }

  const title = aiming ? `${aiming.name} — at which cog?`
    : track ? 'which one?' : 'what would you use?'

  return (
    <div className="flex flex-col gap-1 rounded-lg border border-sky-600/40 bg-sky-50/80 px-2 py-1.5">
      <div className="flex items-center justify-between text-[9px] font-black uppercase tracking-wider text-sky-800">
        <span className="truncate">{title}</span>
        <button type="button" onMouseDown={stopDrag} onClick={onDone}
                className="shrink-0 opacity-60 hover:opacity-100">✕</button>
      </div>

      {aiming ? (
        <div className="flex flex-wrap gap-1">
          <button type="button" onMouseDown={stopDrag} onClick={() => setAiming(null)}
                  className="rounded px-1 py-0.5 text-[10px] font-black opacity-60 hover:opacity-100">←</button>
          {cogs.map((row, i) => (
            <button
              key={i} type="button" onMouseDown={stopDrag}
              onClick={() => send(aiming, i)}
              className="rounded border border-sky-700/40 bg-white/70 px-2 py-0.5 text-[10px] font-extrabold text-sky-900 hover:bg-white"
            >
              {i + 1}. {row.name || `cog ${i + 1}`}
            </button>
          ))}
        </div>
      ) : !track ? (
        <div className="flex flex-wrap gap-1">
          {tracks.map((name) => (
            <button
              key={name} type="button" onMouseDown={stopDrag}
              onClick={() => setTrack(name)}
              className={`track-${name} rounded border px-2 py-0.5 text-[10px] font-extrabold capitalize`}
            >
              {name.replace('_', '-')}
            </button>
          ))}
          {model.fires_left > 0 && cogs.length > 0 && (
            <button
              type="button" onMouseDown={stopDrag}
              onClick={() => choose({ fire: true, name: 'Pink slip' })}
              className="rounded border border-rose-600/40 bg-rose-50 px-2 py-0.5 text-[10px] font-extrabold text-rose-800"
            >
              pink slip
            </button>
          )}
          <button
            type="button" onMouseDown={stopDrag}
            onClick={() => choose({ pass: true, name: 'Pass' })}
            className="rounded border border-amber-700/30 bg-amber-100/70 px-2 py-0.5 text-[10px] font-extrabold text-amber-900"
          >
            pass
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-1">
          <button type="button" onMouseDown={stopDrag} onClick={() => setTrack(null)}
                  className="rounded px-1 py-0.5 text-[10px] font-black opacity-60 hover:opacity-100">←</button>
          {pouch.filter((row) => row.track === track).map((row) => (
            <button
              key={row.level} type="button" onMouseDown={stopDrag}
              onClick={() => choose(row)}
              title={`${row.name} — carrying ${row.count}`}
              className={`track-${row.track} flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-extrabold`}
            >
              <span>{row.name}</span>
              <span className="opacity-60">×{row.count}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// THE FEEDBACK RECEIPT.
//
// A receipt, not a question. The move was READ off the pouch rather
// than asked for, so the ordinary round needs no answer and this exists
// to be glanced at and ignored. It says what went into the log while
// the player still remembers the round, which is the only moment that
// memory is worth anything.
//
// `feedback_showing` is decided in Python, beside every other decision
// the panel makes, so the strip cannot outlive its row because a window
// was left open.
function FeedbackReceipt({ model }) {
  const [asking, setAsking] = useState(false)

  // Collapse the picker whenever the row underneath it goes away --
  // otherwise it hangs over the NEXT round and corrects a row the
  // player never looked at.
  useEffect(() => {
    if (!model.feedback_showing) setAsking(false)
  }, [model.feedback_showing])

  if (!model.feedback_showing) return null

  const cogs = model.rows || []
  const problem = model.feedback_problem

  return (
    <div
      className={`flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[9.5px] font-extrabold ${
        problem
          ? 'border-amber-500/50 bg-amber-100/70 text-amber-900'
          : 'border-emerald-600/30 bg-emerald-50/70 text-emerald-900'
      }`}
    >
      <span className="shrink-0 text-[10px]">{problem ? '⚠' : '✓'}</span>

      <div className="min-w-0 flex-1 truncate">
        {problem ? (
          <>not logged — {problem}</>
        ) : (
          <>
            {/* WHICH KIND OF LABEL, always said out loud. Treating an
                inference as though it were a statement is the mistake
                the two fields exist to keep apart. */}
            {model.feedback_stated ? 'you said: ' : 'logged: '}
            <span className="font-black">{model.feedback_move}</span>
            {model.feedback_against && (
              <span className="opacity-70">
                {' '}· differs from {model.feedback_against}
              </span>
            )}
          </>
        )}
      </div>

      {model.feedback_fixable && !asking && (
        <button
          type="button"
          onClick={() => setAsking(true)}
          onMouseDown={stopDrag}
          className="shrink-0 rounded border border-current/30 px-1.5 py-0.5 opacity-70 hover:opacity-100"
        >
          wrong?
        </button>
      )}

      {asking && (
        <div className="flex shrink-0 items-center gap-1">
          {/* Naming the cog is the ONLY field that can be edited: the
              gag came off the pouch exactly, so a player disagreeing
              with it means something else is wrong and the row should
              go rather than be patched into something plausible. */}
          {model.feedback_needs_target && cogs.map((row, i) => (
            <button
              key={i}
              type="button"
              title={`aimed at ${row.name || `cog ${i + 1}`}`}
              onMouseDown={stopDrag}
              onClick={() => { call('correct_feedback', i, false); setAsking(false) }}
              className="rounded border border-current/30 px-1.5 py-0.5 hover:bg-white/60"
            >
              {i + 1}
            </button>
          ))}
          <button
            type="button"
            onMouseDown={stopDrag}
            onClick={() => { call('correct_feedback', null, true); setAsking(false) }}
            className="rounded border border-rose-600/40 bg-rose-50 px-1.5 py-0.5 text-rose-800 hover:bg-rose-100"
          >
            discard
          </button>
          <button
            type="button"
            onMouseDown={stopDrag}
            onClick={() => setAsking(false)}
            className="rounded px-1 py-0.5 opacity-60 hover:opacity-100"
          >
            ✕
          </button>
        </div>
      )}
    </div>
  )
}

const stopDrag = (e) => {
  e.stopPropagation()
}

function healthClass(h) {
  if (h > 0.6) return 'bg-emerald-500'
  if (h > 0.25) return 'bg-amber-500'
  return 'bg-rose-500'
}

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
  const defeated = (row.health ?? 0) <= 0
  const art = cogArt(row.art, row.department)
  const magnetArt = lureIcon || gagArt('lure', 5)

  return (
    <div
      className={`relative flex items-center gap-1.5 rounded-xl px-2 py-1 transition-all duration-200 min-w-0 border-2 ${
        targeted
          ? 'cog-target-highlight border-amber-500 bg-amber-100 shadow-md'
          : defeated
          ? 'bg-amber-900/5 border-dashed border-amber-900/20 opacity-55 saturate-50'
          : 'bg-white border-amber-900/10 hover:border-amber-900/20 shadow-xs'
      }`}
      onMouseDown={stopDrag}
    >
      {/* AVATAR */}
      <div className="relative size-6.5 shrink-0 rounded-full bg-amber-100 ring-2 ring-amber-900/15 overflow-hidden shadow-inner">
        {art ? (
          <img
            src={art}
            alt=""
            className={`size-full rounded-full object-cover ${row.identified ? '' : 'opacity-45 saturate-50'}`}
          />
        ) : null}
      </div>

      {/* COG LEVEL -- a picker when the reader could not settle it */}
      {row.level ? (
        <span className="w-3.5 shrink-0 text-right font-black text-[10.5px] text-amber-950 opacity-80">
          {row.level}
        </span>
      ) : (
        <select
          className="w-8 h-[20px] shrink-0 rounded-md border-2 border-amber-500 bg-amber-50 text-[10px] font-black text-amber-950 cursor-pointer focus:outline-none px-0"
          title="The level could not be read. Pick it from the plate."
          value=""
          onMouseDown={stopDrag}
          onChange={(e) => call('set_cog_level', row.index, Number(e.target.value))}
        >
          <option value="" disabled>?</option>
          {Array.from({ length: 12 }, (_, i) => i + 1).map((n) => (
            <option key={n} value={n}>{n}</option>
          ))}
        </select>
      )}

      {/* COG NAME PICKER */}
      <CogPicker
        row={row}
        onPick={(key) => call('name_cog', row.index, key)}
      />

      {/* STATUS BADGE: LURED */}
      <div className="flex items-center gap-1 shrink-0">
        {/* LURED / AWAKE BUTTON */}
        <button
          type="button"
          className={`flex shrink-0 items-center gap-0.5 rounded-lg px-1.5 py-0.5 text-[8.5px] font-black uppercase tracking-wide transition-all active:scale-95 cursor-pointer toontown-btn-3d ${
            row.lured
              ? 'border-2 border-emerald-600 bg-emerald-100 text-emerald-950 shadow-xs'
              : 'border border-rose-300 bg-rose-50 text-rose-900 opacity-80 hover:opacity-100'
          }`}
          onMouseDown={stopDrag}
          onClick={() => call('mark_lured', row.index, !row.lured)}
          title={
            row.lured
              ? 'LURED (Asleep): Throw & Squirt hit with bonus; Drop misses. Click to wake up.'
              : 'UNLURED (Awake): Click to mark lured/asleep.'
          }
        >
          {magnetArt ? (
            <img
              src={magnetArt}
              alt=""
              className={`size-3 object-contain ${row.lured ? '' : 'grayscale opacity-60'}`}
            />
          ) : (
            <span>🧲</span>
          )}
          <span>{row.lured ? 'LURED' : 'AWAKE'}</span>
        </button>
      </div>

      {/* HEALTH BAR & ABSOLUTE HP / PERCENTAGE */}
      <div className="flex items-center gap-1.5 flex-1 min-w-[50px] justify-end">
        <div className="h-[6px] flex-1 max-w-[50px] min-w-[16px] overflow-hidden rounded-full bg-amber-900/10 border border-amber-900/10 p-[0.5px]">
          <div
            className={`h-full rounded-full transition-[width] duration-300 ${healthClass(
              row.health,
            )}`}
            style={{ width: `${Math.max(4, row.health * 100)}%` }}
          />
        </div>
        <span className={`shrink-0 text-right font-black text-[9.5px] tabular-nums ${defeated ? 'text-rose-700 opacity-60 font-semibold' : 'text-amber-950 opacity-85'}`}>
          {row.hp !== null && row.hp !== undefined && row.max_hp !== null && row.max_hp !== undefined
            ? `${row.hp}/${row.max_hp}`
            : (defeated ? '0%' : `${Math.round(row.health * 100)}%`)}
        </span>
      </div>
    </div>
  )
}

// THE ENGINES, in the order their rows are drawn. `rl` is `hybrid.climb`,
// which is the trained policy -- shown as PPO because that is what a
// player knows it as.
const ENGINE_LABEL = { rl: 'PPO', search: 'SEARCH', playout: 'PLAYOUT' }
const ENGINE_BADGE = {
  rl: 'bg-emerald-600 text-white border-emerald-700',
  search: 'bg-sky-600 text-white border-sky-700',
  playout: 'bg-violet-600 text-white border-violet-700',
}

function engineAnswer(model, engine) {
  const pick = (field) => model[`${engine}_${field}`]
  const ready = engine === 'rl' ? Boolean(model.rl_gag) : Boolean(pick('ready'))
  return {
    engine,
    gag: pick('gag') || '',
    track: pick('track') || '',
    level: pick('gag_level') || 0,
    accuracy: pick('accuracy'),
    reason: pick('reason') || '',
    organic: Boolean(pick('organic')),
    note: engine === 'playout' ? (model.playout_note || '') : '',
    // ANYTIME: the playouts keep refining after the first move is up.
    refining: engine === 'playout' && ready && !model.playout_done,
    rollouts: engine === 'playout' ? (model.playout_rollouts || 0) : 0,
    ready,
  }
}

function Refining({ answer }) {
  if (!answer.rollouts) return null
  return answer.refining ? (
    <span className="inline-flex items-center gap-1 text-[8px] font-black uppercase text-violet-700">
      <span className="loading loading-dots loading-xs text-violet-500" />
      refining · {answer.rollouts} playouts
    </span>
  ) : (
    <span className="text-[8px] font-black uppercase text-violet-700/70">
      {answer.rollouts} playouts
    </span>
  )
}

function EngineRow({ answer, model, isStale, hero }) {
  const art = answer.track && answer.level ? gagArt(answer.track, answer.level) : null
  const hasAcc = answer.accuracy !== null && answer.accuracy !== undefined
  // "Thinking" only while that engine is actually working; otherwise say
  // why there is nothing, rather than spin on a board nobody is solving.
  const working = answer.engine === 'playout' ? Boolean(model.playout_pending) : Boolean(model.thinking)
  const thinking = !answer.ready && working
  const idle = !answer.ready && !working
  const same = answer.ready && answer.gag && answer.gag === hero
  return (
    <div className={`rounded-xl border-2 border-amber-900/15 bg-amber-50/90 px-2 py-1.5 shadow-xs flex items-center justify-between gap-2 ${
      isStale ? 'opacity-65 grayscale-[40%] saturate-50' : ''
    }`}>
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <span className={`badge h-[18px] w-[58px] justify-center px-1 text-[8px] font-black uppercase tracking-wider border shadow-2xs shrink-0 ${ENGINE_BADGE[answer.engine]}`}>
          {ENGINE_LABEL[answer.engine]}
        </span>
        {art && !thinking && (
          <div className="flex size-6 shrink-0 items-center justify-center">
            <img src={art} alt="" className="size-full object-contain drop-shadow-xs" />
          </div>
        )}
        <div className="min-w-0 flex-1">
          {thinking ? (
            <span className="inline-flex items-center gap-1.5 text-[10.5px] font-bold text-sky-700">
              <span className="loading loading-dots loading-xs text-sky-600" />
              Thinking...
            </span>
          ) : idle ? (
            <span className="text-[10px] font-bold text-amber-900/50">
              {model.problems && model.problems.length ? 'waiting for a readable board' : '—'}
            </span>
          ) : answer.gag ? (
            <>
              <div className="flex items-center gap-1 flex-wrap">
                <span className="text-[11px] font-black text-amber-950 truncate">{answer.gag}</span>
                {answer.organic && <OrganicLeaf icon={model.organic_icon} size="size-3" />}
                {same && (
                  <span className="text-[8px] font-black uppercase text-emerald-700">agrees</span>
                )}
                <Refining answer={answer} />
              </div>
              {(answer.reason || hasAcc) && (
                <div className="text-[9px] font-extrabold italic text-amber-900/80 flex items-center gap-1 flex-wrap">
                  {answer.reason && <span>{answer.reason}</span>}
                  {answer.reason && hasAcc && <span>·</span>}
                  {hasAcc && <span className="text-emerald-800 font-bold not-italic">{answer.accuracy}% acc</span>}
                </div>
              )}
            </>
          ) : (
            <span className="text-[10px] font-bold text-amber-900/60">{answer.note || 'no move'}</span>
          )}
        </div>
      </div>
      {answer.ready && answer.gag && !same && (
        <button
          type="button"
          onMouseDown={stopDrag}
          onClick={() => call('prefer_engine', answer.engine)}
          className="shrink-0 btn btn-xs h-[22px] min-h-0 bg-white border border-amber-900/20 text-amber-950 font-black text-[9px] hover:bg-amber-100 toontown-btn-3d px-2 cursor-pointer"
          title={`Show ${ENGINE_LABEL[answer.engine]}'s move`}
        >
          Use ➔
        </button>
      )}
    </div>
  )
}

function Advice({ model }) {
  const activeEngine = model.engine || model.preferred_engine || 'rl'
  const showing = Boolean(model.advice) && model.in_battle
  const track = showing && model.track ? model.track : 'none'
  const firing = showing && model.track === 'fire'
  const calling = showing && model.track === 'sos'
  const art = showing && !firing && !calling
    ? gagArt(model.track, model.gag_level) : null

  // Staleness check: non-empty problems means the advice on screen is out of date
  const isStale = Boolean(model.problems && model.problems.length > 0)

  // Engine specific primary values
  const primary = engineAnswer(model, activeEngine)
  const primaryReason = primary.reason || model.reason
  const primaryAccuracy = primary.accuracy !== null && primary.accuracy !== undefined
    ? primary.accuracy : model.accuracy
  const primaryOrganic = primary.organic || model.organic

  const hasWhy = showing && (Boolean(primaryReason) || (primaryAccuracy !== null && primaryAccuracy !== undefined))
  const hasPressure = model.in_battle && (model.incoming !== null || model.survive !== null)

  // EVERY OTHER ENGINE, side by side, each thinking or answered on its
  // own clock -- PPO in milliseconds, the playouts and the search later.
  const others = (model.engines || ['rl', 'search', 'playout'])
    .filter((e) => e !== activeEngine && ENGINE_LABEL[e])
    .map((e) => engineAnswer(model, e))
  const showOthers = model.in_battle && others.length > 0

  return (
    <div className="space-y-1.5">
      {/* 0-TURN INSTANT UNITE BANNER */}
      {showing && model.unite && (
        <div className="flex items-center gap-2 rounded-xl border-2 border-emerald-500 bg-emerald-50 px-2.5 py-1 text-emerald-950 shadow-md animate-pulse">
          <div className="flex size-6 shrink-0 items-center justify-center rounded-md bg-emerald-500 text-white shadow-xs">
            <UniteFist size="size-3.5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[8.5px] font-black tracking-widest uppercase text-emerald-700">
              USE UNITE FIRST (0-TURN INSTANT)
            </div>
            <div className="text-[11.5px] font-black tracking-wide text-emerald-950 truncate">
              {model.unite}
            </div>
          </div>
        </div>
      )}

      {/* MAIN HERO ACTION CARD */}
      <div className={`track-${track} toontown-card-hero relative flex items-center gap-2.5 overflow-hidden rounded-xl p-2.5 shadow-md transition-all ${
        isStale ? 'opacity-65 grayscale-[40%] saturate-50 border-2 border-amber-500/50' : ''
      }`}>
        {/* No plate behind the gag art. The PNGs are cut out with a real
            alpha channel, so a white chip was throwing away transparency
            they already have; the icon sits on the track tint instead,
            with a drop shadow to lift it off. */}
        {art && (
          <div className="flex size-10.5 shrink-0 items-center justify-center">
            <img src={art} alt="" className="size-full object-contain drop-shadow-sm" />
          </div>
        )}

        {firing && (
          <div className="flex size-10.5 shrink-0 items-center justify-center rounded-lg bg-rose-100 border border-rose-400 shadow-xs">
            <PinkSlip size="size-8" />
          </div>
        )}

        {calling && (
          <div className="flex size-10.5 shrink-0 items-center justify-center rounded-lg bg-amber-100 border border-amber-400 shadow-xs">
            <SosCard size="size-8" />
          </div>
        )}

        <div className="min-w-0 flex-1">
          {showing && model.track && (
            <div className="flex items-center gap-1.5 flex-wrap">
              <span
                className="text-[9.5px] font-black tracking-widest uppercase"
                style={{ color: 'var(--track-text)' }}
              >
                {firing ? '🔥 PINK SLIP · FIRE'
                  : calling ? '⭐ SOS CALL'
                    : model.track.replace('_', '-').toUpperCase()}
              </span>
              {model.gag_level && !firing && !calling && (
                <span className="rounded-full bg-white/90 px-1.5 py-0.2 text-[9px] font-black text-amber-950 border border-amber-900/15">
                  LVL {model.gag_level}
                </span>
              )}
              {primaryOrganic && (
                <OrganicLeaf icon={model.organic_icon} />
              )}
              {ENGINE_LABEL[activeEngine] && (
                <span className={`rounded px-1 py-0.2 text-[8px] font-black uppercase tracking-wider border ${ENGINE_BADGE[activeEngine]}`}>
                  {ENGINE_LABEL[activeEngine]}
                </span>
              )}
              <Refining answer={primary} />
              {isStale && (
                <span className="rounded bg-amber-200/90 text-amber-950 border border-amber-400/60 px-1.5 py-0.2 text-[8px] font-black uppercase tracking-wider shadow-2xs">
                  ⚠️ STALE
                </span>
              )}
            </div>
          )}

          <div
            className={
              showing
                ? 'text-[14px] font-black leading-snug tracking-tight text-amber-950'
                : 'text-[12.5px] font-bold opacity-75 text-amber-950'
            }
          >
            {model.thinking && !showing ? (
              <span className="inline-flex items-center gap-1.5 text-sky-700 font-bold">
                <span className="loading loading-dots loading-xs text-sky-600" />
                computing best strategy...
              </span>
            ) : (
              model.advice || (model.in_battle
                ? 'no move to recommend'
                : 'waiting for a battle')
            )}
          </div>

          {/* THE WHY-LINE (reason & accuracy) */}
          {hasWhy && (
            <div className="text-[10.5px] font-extrabold italic opacity-90 mt-0.5 text-amber-900/90 flex items-center gap-1.5 flex-wrap">
              {primaryReason && <span>{primaryReason}</span>}
              {primaryReason && primaryAccuracy !== null && primaryAccuracy !== undefined && <span>·</span>}
              {primaryAccuracy !== null && primaryAccuracy !== undefined && (
                <span className="bg-white/80 px-1.5 py-0.2 rounded-md border border-amber-900/15 text-[9px] font-black not-italic text-emerald-800 shadow-2xs">
                  {primaryAccuracy}% acc
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* THE OTHER ENGINES */}
      {showOthers && (
        <div className="space-y-1">
          {others.map((answer) => (
            <EngineRow key={answer.engine} answer={answer} model={model}
              isStale={isStale} hero={model.advice} />
          ))}
        </div>
      )}

      {/* BOARD PRESSURE GAUGE (incoming & survive) */}
      {hasPressure && (
        <div className="flex items-center justify-between gap-2 px-2.5 py-1 rounded-xl bg-white border border-amber-900/10 shadow-2xs text-[10px] font-black">
          {model.incoming !== null && model.incoming !== undefined ? (
            <div className="flex items-center gap-1 text-amber-950">
              <span className="text-amber-600">⚡</span>
              <span>Incoming:</span>
              <span className="font-mono text-[10.5px] text-rose-700">{Math.round(model.incoming)} HP</span>
            </div>
          ) : (
            <div />
          )}

          {model.survive !== null && model.survive !== undefined && (
            <div className="flex items-center gap-1 ml-auto">
              <span className="text-sky-600">🛡️</span>
              <span>Survive:</span>
              <span className={`px-1.5 py-0.2 rounded-md text-[9.5px] font-black ${
                model.survive < 2.0
                  ? 'bg-rose-100 text-rose-900 border border-rose-300 animate-pulse'
                  : 'bg-emerald-100 text-emerald-900 border border-emerald-300'
              }`}>
                {model.survive >= 4.0 ? '4+ rounds' : `${model.survive.toFixed(1)} rounds`}
              </span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function StepperRow({ label, subtitle, badge, icon, value, onChange, title }) {
  return (
    <div
      className="flex items-center justify-between gap-2 px-1.5 py-0.5 rounded-lg hover:bg-amber-100/40 transition-colors"
      title={title}
      onMouseDown={stopDrag}
    >
      <div className="flex items-center gap-1.5 min-w-0">
        {icon}
        <div className="min-w-0">
          <div className="flex items-center gap-1">
            <span className="text-[11.5px] font-extrabold text-amber-950 tracking-wide truncate">
              {label}
            </span>
            {badge && (
              <span className="text-[8px] font-black uppercase px-1 py-0.2 rounded bg-amber-200/80 text-amber-900/70 border border-amber-900/15">
                {badge}
              </span>
            )}
          </div>
          {subtitle && (
            <div className="text-[8.5px] font-extrabold text-amber-900/50 -mt-0.5">
              {subtitle}
            </div>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1 shrink-0 bg-amber-100/70 px-1 py-0.5 rounded-lg border border-amber-900/10 shadow-inner">
        <button
          type="button"
          className="flex size-5 items-center justify-center rounded bg-white text-[12px] font-black text-amber-950 hover:bg-amber-500 hover:text-white active:translate-y-0.5 transition-all disabled:opacity-30 cursor-pointer toontown-btn-3d border border-amber-900/10"
          disabled={value <= 0}
          onMouseDown={stopDrag}
          onClick={() => onChange(Math.max(0, value - 1))}
        >
          –
        </button>
        <input
          type="number"
          min="0"
          max="99"
          value={value}
          onMouseDown={stopDrag}
          onKeyDown={(e) => e.stopPropagation()}
          onChange={(e) => {
            const raw = e.target.value
            if (raw === '') {
              onChange(0)
              return
            }
            const parsed = parseInt(raw, 10)
            if (!isNaN(parsed)) {
              onChange(Math.max(0, Math.min(99, parsed)))
            }
          }}
          className="w-6 h-5 text-center font-black text-[12px] tabular-nums bg-transparent text-amber-950 focus:outline-none focus:bg-white focus:ring-1 focus:ring-amber-500 rounded no-drag select-text [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none cursor-text"
        />
        <button
          type="button"
          className="flex size-5 items-center justify-center rounded bg-white text-[12px] font-black text-amber-950 hover:bg-amber-500 hover:text-white active:translate-y-0.5 transition-all cursor-pointer toontown-btn-3d border border-amber-900/10"
          onMouseDown={stopDrag}
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
  // Which width of "no, not that" the player is choosing. False = closed.
  const [rejecting, setRejecting] = useState(false)
  // Collapsed whenever the board moves: a picker left open across a
  // round would attach the next answer to a position the player is no
  // longer looking at.
  const [suggesting, setSuggesting] = useState(false)
  useEffect(() => { setSuggesting(false) }, [model.advice, model.in_battle])

  // Labels for the reject popup. The gag's name is the advice text up to
  // " on ", which is how `advise._render` builds it; the track comes off
  // the model rather than being parsed back out of the sentence.
  const gagLabel = model.advice ? model.advice.split(' on ')[0] : ''
  const trackLabel = model.track && model.track !== 'fire' && model.track !== 'sos'
    ? model.track.split('_').map((w) => w[0].toUpperCase() + w.slice(1)).join('-')
    : ''
  // The gag's own art, and the track's Silly Team badge. The badges are
  // read from the player's install at runtime like the lure magnet, so
  // `track_icons` is empty when the game is not there and each button
  // simply shows its word.
  const rejectGagArt = gagArt(model.track, model.gag_level)
  const rejectTrackArt = (model.track_icons || {})[model.track] || null

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
    const t1 = setTimeout(send, 60)
    const t2 = setTimeout(send, 300)
    if (document.fonts?.ready) {
      document.fonts.ready.then(send)
    }
    if (typeof ResizeObserver === 'undefined') {
      return () => { clearTimeout(t1); clearTimeout(t2) }
    }
    const ro = new ResizeObserver(send)
    ro.observe(panel)
    return () => {
      clearTimeout(t1)
      clearTimeout(t2)
      ro.disconnect()
    }
  }, [])

  const locationText = [model.district, model.neighborhood, model.zone].filter(Boolean).join(' · ')

  return (
    <div id="panel" className="flex flex-col gap-2 bg-[#F4F1EA] p-2.5 text-amber-950 select-none">
      {/* HEADER / STATUS BLOCK */}
      <div className="window-drag-region flex items-start justify-between gap-2 border-b-2 border-amber-900/10 pb-1.5 cursor-move">
        <div className="flex items-start gap-2 min-w-0">
          <span
            className={`mt-1 inline-block size-2.5 shrink-0 rounded-full ${
              model.in_battle
                ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)] animate-pulse'
                : 'bg-emerald-600/80'
            }`}
          />
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <h1 className="text-[12.5px] font-black uppercase tracking-wide text-amber-950">
                {model.in_battle
                  ? (model.status && model.status.toLowerCase() !== 'in battle'
                    ? `IN BATTLE (${model.status.toUpperCase()})`
                    : 'IN BATTLE')
                  : 'WAITING FOR BATTLE'}
              </h1>
              {model.engine && (() => {
                const currentEngine = model.preferred_engine || model.engine || 'rl'
                const isRl = currentEngine === 'rl'
                return (
                  <button
                    type="button"
                    onMouseDown={stopDrag}
                    onClick={() => call('prefer_engine', isRl ? 'search' : 'rl')}
                    className={`badge h-[18px] px-2 text-[8.5px] font-black tracking-widest cursor-pointer toontown-btn-3d border ${
                      isRl
                        ? 'bg-emerald-500 text-white border-emerald-700 hover:bg-emerald-600 shadow-xs'
                        : 'bg-sky-500 text-white border-sky-700 hover:bg-sky-600 shadow-xs'
                    }`}
                    title={
                      isRl
                        ? 'Currently displaying RL policy move. Click to swap to expectimax search.'
                        : 'Currently displaying expectimax search move. Click to swap to RL policy.'
                    }
                  >
                    {isRl ? 'RL' : 'SEARCH'}
                    {model.preferred_engine === 'search' && !model.search_ready ? '…' : ''}
                  </button>
                )
              })()}
            </div>
            <p className="text-[10px] font-extrabold text-amber-900/60 mt-0.2 truncate">
              {model.evidence || (model.in_battle ? 'Battle active' : 'No active battle detected on cluster')}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          {model.turn > 0 && (
            <span className="font-black text-[10px] text-amber-900/60"
                  title="estimated from the gag menu opening; misses rounds you let time out">
              {/* A WORD, not "~". At 10px the tilde flattens into a dash and
                  "turn ~1" was read as "turn -1" in live play. */}
              est. turn {model.turn}
            </span>
          )}
          <button
            type="button"
            onMouseDown={stopDrag}
            className="flex size-5 items-center justify-center rounded-md bg-amber-200/60 text-[11px] font-black text-amber-950 hover:bg-amber-300 active:translate-y-0.5 transition-all cursor-pointer border border-amber-900/20"
            onClick={() => call('close')}
            title="Close overlay"
          >
            ✕
          </button>
        </div>
      </div>

      {/* ADVICE HERO & COG ROSTER */}
      <Advice model={model} />

      <div className="min-h-[6px] space-y-1">
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
          <div className={`space-y-0.5 text-[10.5px] font-bold ${model.in_battle ? 'pt-0.5 text-amber-800' : 'pt-0.2 text-amber-900/60'
            }`}>
            {model.problems.slice(0, 4).map((line, i) => (
              <div key={i} className="flex items-center gap-1">
                <span>⚠️</span> <span>{line}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* SECTION 1: SOLVER CONFIGURATION */}
      <div className="space-y-1">
        <div className="text-[9px] font-black tracking-widest text-amber-900/60 uppercase">
          SOLVER CONFIGURATION
        </div>
        <div className="toontown-card-panel p-2 space-y-2 rounded-xl">
          {/* Row 1: Objective Preset (Left) + Toon Party (Right) */}
          <div className="flex items-center justify-between gap-2.5">
            <div
              className="flex-1 min-w-0 space-y-0.5"
              title="How to play: Survive guards laff, Conserve saves gags, Speedrun ends fights fast, Glass Cannon spends freely. Shapes the Search and Playout rows; PPO always plays the same way."
            >
              <label className="block text-[8.5px] font-black uppercase tracking-wide text-amber-900/60">Preset</label>
              <select
                className="select select-xs h-[26px] min-h-0 w-full bg-amber-50 font-extrabold text-[10.5px] text-amber-950 border-2 border-amber-900/15 rounded-lg cursor-pointer focus:outline-none focus:border-sky-500 px-1.5"
                onMouseDown={stopDrag}
                value={model.objective}
                onChange={(e) => call('set_objective', e.target.value)}
              >
                {OBJECTIVES.map((o) => (
                  <option key={o} value={o}>
                    {o.charAt(0).toUpperCase() + o.slice(1)}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-0.5 shrink-0">
              <div className="flex justify-between items-center text-[8.5px] font-black uppercase tracking-wide text-amber-900/60 gap-1.5">
                <span>Toon Party</span>
                <button
                  type="button"
                  onMouseDown={stopDrag}
                  onClick={() => call('set_level_7', !model.allow_level_7)}
                  className={`text-[8.5px] font-black uppercase px-1 py-0.2 rounded cursor-pointer active:translate-y-0.5 transition-all toontown-btn-3d border ${
                    model.allow_level_7
                      ? 'text-emerald-950 bg-emerald-200 border-emerald-400'
                      : 'text-amber-950 bg-amber-200 border-amber-400'
                  }`}
                  title={model.allow_level_7 ? 'Level 7s allowed. Click to hold back.' : 'Level 7s held back. Click to allow.'}
                >
                  {model.allow_level_7 ? '7s ON' : '7s OFF'}
                </button>
              </div>
              <div className="join">
                {[1, 2, 3, 4].map((n) => (
                  <button
                    key={n}
                    type="button"
                    onMouseDown={stopDrag}
                    className={`btn btn-xs join-item h-[26px] min-h-0 w-[25px] text-[10.5px] font-black cursor-pointer active:translate-y-0.5 transition-all toontown-btn-3d ${
                      model.toon_count === n
                        ? 'bg-sky-500 border-2 border-sky-700 text-white shadow-xs'
                        : 'bg-amber-100/60 border border-amber-900/15 text-amber-950 opacity-70 hover:opacity-100'
                    }`}
                    onClick={() => call('set_toon_count', n)}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Row 2: Full-width Think Time Slider */}
          <div className="space-y-0.5 pt-1 border-t border-amber-900/10">
            <div className="flex justify-between items-center text-[8.5px] font-black uppercase tracking-wide text-amber-900/60">
              <span>Think Time</span>
              <span className="font-black text-sky-700 text-[11px]">{Math.round(model.budget)}s</span>
            </div>
            <input
              type="range" min="3" max="45" step="1"
              className="range range-xs range-primary w-full cursor-pointer accent-sky-500"
              onMouseDown={stopDrag}
              onPointerDown={stopDrag}
              value={model.budget}
              onChange={(e) => call('set_budget', Number(e.target.value))}
            />
            <div className="flex justify-between text-[8.5px] font-black text-amber-900/50">
              <span>3s</span>
              <span>45s max</span>
            </div>
          </div>
        </div>
      </div>

      {/* SECTION 2: BATTLE CONTEXT & INVENTORY */}
      <div className="space-y-1">
        <div className="text-[9px] font-black tracking-widest text-amber-900/60 uppercase">
          BATTLE CONTEXT & INVENTORY
        </div>
        <div className="toontown-card-panel p-1.5 space-y-0.5 rounded-xl">
          <div
            className="flex items-center justify-between gap-2 px-1.5 py-0.5"
            onMouseDown={stopDrag}
            title="Which boss fight this is. Detected where the game says so; pick it by hand otherwise."
          >
            <div className="min-w-0">
              <div className="text-[11.5px] font-extrabold text-amber-950 tracking-wide">Boss Fight</div>
              <div className="text-[8.5px] font-extrabold text-amber-900/50 -mt-0.5">
                {model.boss_kind && !model.boss_manual ? 'Detected' : 'Pick by hand'}
              </div>
            </div>
            <select
              className="select select-xs h-[24px] min-h-0 w-[72px] bg-amber-50 font-extrabold text-[10.5px] text-amber-950 border-2 border-amber-900/15 rounded-lg cursor-pointer focus:outline-none focus:border-sky-500 px-1.5"
              onMouseDown={stopDrag}
              value={model.boss_manual || model.boss_kind}
              onChange={(e) => call('set_boss', e.target.value)}
            >
              {BOSSES.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </div>
          {model.boss_kind && (
            <StepperRow
              label="Cogs Defeated"
              subtitle={model.cogs_left >= 0 ? `${model.cogs_left} left` : 'Fight size unknown'}
              value={model.cogs_defeated}
              onChange={(val) => call('set_cogs_defeated', val)}
              title="Cogs defeated this boss fight. Counted automatically; correct it if it drifts."
            />
          )}
          <StepperRow
            label="Pink Slips"
            icon={<PinkSlip size="size-4.5" />}
            value={model.max_fires}
            onChange={(val) => call('set_max_fires', val)}
            title="Max Pink Slips allowed (0 = never fire)"
          />
          <StepperRow
            label="Resistance Unites"
            icon={<UniteFist size="size-4.5" />}
            value={model.max_unites}
            onChange={(val) => call('set_max_unites', val)}
            title="Unites you hold. The advice plans around them and may suggest one beside the gag (0 = never unite)."
          />
          <StepperRow
            label="SOS Cards"
            badge="Inert on TTR"
            icon={<SosCard size="size-4.5" />}
            value={model.max_sos}
            onChange={(val) => call('set_max_sos', val)}
            title="Max SOS cards allowed (0 = never use SOS) — Inert on TTR"
          />
        </div>
      </div>

      {/* SECTION 3: MANUAL OVERRIDES */}
      <div className="flex items-center justify-between gap-2 pt-1 border-t-2 border-amber-900/10">
        <span className="text-[10px] font-black uppercase tracking-wide text-amber-900/60">
          Manual Overrides
        </span>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onMouseDown={stopDrag}
            className={`btn btn-sm h-[28px] min-h-0 text-[10.5px] font-black tracking-wide px-2.5 toontown-btn-3d cursor-pointer ${
              model.in_battle
                ? 'bg-rose-500 border-2 border-rose-700 text-white hover:bg-rose-600'
                : 'bg-emerald-500 border-2 border-emerald-700 text-white hover:bg-emerald-600'
            }`}
            disabled={!model.can_confirm}
            onClick={() => call('toggle_fight')}
          >
            {model.in_battle ? 'Fight is over' : 'Force Fight State'}
          </button>
          <div className="relative">
            <button
              type="button"
              onMouseDown={stopDrag}
              className="btn btn-sm h-[28px] min-h-0 bg-amber-200 border-2 border-amber-400 text-amber-950 hover:bg-amber-300 text-[10.5px] font-black px-2.5 toontown-btn-3d cursor-pointer disabled:opacity-30"
              disabled={!model.can_advise || !model.advice}
              onClick={() => setRejecting((open) => !open)}
              title="Turn this suggestion down and ask for another"
            >
              Reconsider
            </button>

            {rejecting && (
              <>
                {/* Click anywhere else to back out. */}
                <div
                  className="fixed inset-0 z-40"
                  onMouseDown={stopDrag}
                  onClick={() => setRejecting(false)}
                />
                <div
                  className="reject-pop absolute bottom-full right-0 z-50 mb-2 w-56 rounded-2xl border-[3px] border-amber-500 bg-amber-50 p-2 shadow-lg"
                  onMouseDown={stopDrag}
                >
                  <div className="px-1 pb-1.5 text-center text-[10px] font-black uppercase tracking-wider text-amber-900/70">
                    Nope! Not that&hellip;
                  </div>
                  <div className="flex flex-col gap-1.5">
                    {/* The word carries the choice and the picture says
                        which one -- the gag's own art, and the track's
                        Silly Team badge. Spelling the gag's name out
                        underneath said the same thing twice. */}
                    <button
                      type="button"
                      className="btn btn-xs h-auto min-h-0 w-full justify-between gap-2 rounded-xl border-2 border-sky-500 bg-sky-100 pl-2.5 pr-1.5 py-1 text-left text-sky-950 hover:bg-sky-200 toontown-btn-3d cursor-pointer"
                      onClick={() => { call('reconsider', 'gag'); setRejecting(false) }}
                      title={gagLabel ? `Turn down ${gagLabel}, keep the rest of the track` : 'Turn down just this gag'}
                    >
                      <span className="text-[11px] font-black leading-tight">
                        Not this <span className="text-[13px]">Gag</span>
                      </span>
                      {rejectGagArt && (
                        <img src={rejectGagArt} alt="" className="size-7 shrink-0 object-contain drop-shadow-xs" />
                      )}
                    </button>
                    <button
                      type="button"
                      className="btn btn-xs h-auto min-h-0 w-full justify-between gap-2 rounded-xl border-2 border-rose-500 bg-rose-100 pl-2.5 pr-1 py-0.5 text-left text-rose-950 hover:bg-rose-200 toontown-btn-3d cursor-pointer"
                      onClick={() => { call('reconsider', 'track'); setRejecting(false) }}
                      title={trackLabel ? `Turn down ${trackLabel} entirely, at every level` : 'Turn down the whole track'}
                    >
                      <span className="text-[11px] font-black leading-tight">
                        Not this <span className="text-[13px]">Track</span>
                      </span>
                      {/* Bigger than the gag's art on purpose: the Silly
                          Team badge is a medallion with a scene inside
                          it, and at the gag's size it reads as a blob. */}
                      {rejectTrackArt && (
                        <img src={rejectTrackArt} alt="" className="size-10 shrink-0 object-contain drop-shadow-sm" />
                      )}
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* SECTION 3.5: FEEDBACK -- receipt, and the "I'd use" picker */}
      {suggesting ? (
        <SuggestPicker model={model} onDone={() => setSuggesting(false)} />
      ) : (
        <div className="flex items-stretch gap-1">
          <div className="min-w-0 flex-1"><FeedbackReceipt model={model} /></div>
          {model.in_battle && (model.pouch || []).length > 0 && (
            <button
              type="button"
              onMouseDown={stopDrag}
              onClick={() => setSuggesting(true)}
              title="tell the solver what you would use here"
              className="shrink-0 self-center rounded-lg border border-sky-600/40 bg-sky-50/70 px-2 py-1 text-[9.5px] font-extrabold text-sky-800 hover:bg-sky-100"
            >
              I'd use…
            </button>
          )}
        </div>
      )}

      {/* SECTION 4: LOCAL API CONNECTION STRIP */}
      <div className="flex items-center justify-between gap-1 px-1 pt-1 border-t border-amber-900/10 text-[9px] font-extrabold text-amber-900/60">
        <div className="flex items-center gap-1 truncate min-w-0">
          <span className="shrink-0 text-[10px]">📍</span>
          <span className="truncate">
            {locationText || 'Local API Disconnected'}
          </span>
        </div>
        {model.discord_floors === 'blocked' && (
          <button
            type="button"
            onMouseDown={stopDrag}
            onClick={() => call('restart_discord')}
            title="Discord is holding the connection the game sends building floors over. Restarting it puts the panel in front: your Discord status keeps working, and floors show here."
            className="shrink-0 rounded border border-sky-600/40 bg-sky-50/80 px-1.5 py-0.2 text-[9px] font-extrabold text-sky-800 hover:bg-sky-100 cursor-pointer"
          >
            Restart Discord to show floors
          </button>
        )}
        {model.discord_floors === 'restarting' && (
          <span className="shrink-0 text-sky-800">Restarting Discord…</span>
        )}
        {model.invasion && (
          <div className="shrink-0 text-amber-900 font-black bg-amber-200/80 px-1.5 py-0.2 rounded border border-amber-400/50 shadow-2xs">
            🤖 {model.invasion}
          </div>
        )}
      </div>
    </div>
  )
}
