import React, { useState, useMemo } from 'react'
import { GagIcon, CogAvatar, DeptIcon, PinkSlip, SosCard, UniteFist, OrganicLeaf } from './Icons'
import { generateScenario, randomToon } from '../api'

const TRACKS = ['toon_up', 'trap', 'lure', 'sound', 'throw', 'squirt', 'drop']

const TRACK_LABELS = {
  toon_up: 'Toon-Up',
  trap: 'Trap',
  lure: 'Lure',
  sound: 'Sound',
  throw: 'Throw',
  squirt: 'Squirt',
  drop: 'Drop',
}

const TRAP_NAMES = [
  'Banana Peel (Lvl 1)',
  'Rake (Lvl 2)',
  'Marbles (Lvl 3)',
  'Quicksand (Lvl 4)',
  'Trapdoor (Lvl 5)',
  'TNT (Lvl 6)',
  'Railroad (Lvl 7)',
]

const GAG_MAX_CARRY = {
  sound: { 1: 20, 2: 15, 3: 15, 4: 10, 5: 5, 6: 2, 7: 1 },
  throw: { 1: 30, 2: 25, 3: 20, 4: 15, 5: 7, 6: 3, 7: 1 },
  squirt: { 1: 30, 2: 25, 3: 20, 4: 15, 5: 7, 6: 3, 7: 1 },
  lure: { 1: 30, 2: 25, 3: 20, 4: 15, 5: 7, 6: 3, 7: 1 },
  toon_up: { 1: 30, 2: 25, 3: 20, 4: 15, 5: 7, 6: 3, 7: 1 },
  drop: { 1: 30, 2: 25, 3: 20, 4: 15, 5: 7, 6: 3, 7: 1 },
  trap: { 1: 30, 2: 25, 3: 20, 4: 15, 5: 7, 6: 3, 7: 1 },
}

function cogMaxHp(level) {
  const l = Number(level) || 1
  return (l + 1) * (l + 2)
}

export default function ScenarioBuilder({
  catalogue,
  initialConfig,
  onApply,
  onClose,
  busy,
}) {
  // Scenario Config State
  const [toons, setToons] = useState(() => {
    if (initialConfig?.toons?.length) return JSON.parse(JSON.stringify(initialConfig.toons))
    if (initialConfig?.toon) return [JSON.parse(JSON.stringify(initialConfig.toon))]
    return [
      {
        laff: 100,
        max_laff: 100,
        organic: 'throw',
        fires: 3,
        unites_held: ['restock_all', 'laff_80'],
        sos_cards: ['Flippy', 'Mr. Freeze'],
        gags: {
          sound: { 4: 10, 5: 5, 6: 2 },
          throw: { 4: 7, 5: 7, 6: 3, 7: 1 },
          squirt: { 4: 7, 5: 7, 6: 3 },
          lure: { 4: 6, 5: 5, 6: 3 },
          toon_up: { 4: 6, 5: 5, 6: 3 },
        },
      },
    ]
  })

  const [cogs, setCogs] = useState(() => {
    if (initialConfig?.cogs?.length) {
      return initialConfig.cogs.map((c) => ({
        dept: c.dept || 'sellbot',
        name: c.name || 'Cold Caller',
        level: c.level || 5,
        hp: c.hp != null ? c.hp : cogMaxHp(c.level || 5),
        max_hp: c.max_hp != null ? c.max_hp : cogMaxHp(c.level || 5),
        lured: Boolean(c.lured),
        lure_rounds: c.lure_rounds || 2,
        trapped: Boolean(c.trapped),
        trap_level: c.trap_level || 6,
        suited: Boolean(c.suited),
      }))
    }
    return [
      {
        dept: 'sellbot',
        name: 'Mr. Hollywood',
        level: 12,
        hp: 182,
        max_hp: 182,
        lured: false,
        lure_rounds: 2,
        trapped: false,
        trap_level: 6,
        suited: false,
      },
      {
        dept: 'lawbot',
        name: 'Legal Eagle',
        level: 11,
        hp: 156,
        max_hp: 156,
        lured: false,
        lure_rounds: 2,
        trapped: false,
        trap_level: 6,
        suited: false,
      },
    ]
  })

  const [activeToonIdx, setActiveToonIdx] = useState(0)
  const [generating, setGenerating] = useState(false)
  const [feedback, setFeedback] = useState(null)

  // Current active toon
  const currentToon = toons[activeToonIdx] || toons[0]

  // Count total pouch gags for active toon
  const currentPouchCount = useMemo(() => {
    if (!currentToon?.gags) return 0
    let sum = 0
    Object.values(currentToon.gags).forEach((trackCounts) => {
      if (trackCounts && typeof trackCounts === 'object') {
        Object.values(trackCounts).forEach((c) => {
          sum += Number(c) || 0
        })
      }
    })
    return sum
  }, [currentToon])

  // Handlers for Toons
  const handleAddToon = () => {
    if (toons.length >= 4) return
    const newToon = {
      laff: 100,
      max_laff: 100,
      organic: null,
      fires: 1,
      unites_held: [],
      sos_cards: [],
      gags: {
        sound: { 4: 10, 5: 5 },
        throw: { 4: 10, 5: 5, 6: 2 },
        squirt: { 4: 10, 5: 5 },
      },
    }
    setToons([...toons, newToon])
    setActiveToonIdx(toons.length)
  }

  const handleRemoveToon = (idx) => {
    if (toons.length <= 1) return
    const updated = toons.filter((_, i) => i !== idx)
    setToons(updated)
    setActiveToonIdx(Math.min(activeToonIdx, updated.length - 1))
  }

  const updateCurrentToon = (patch) => {
    setToons((list) =>
      list.map((t, i) => (i === activeToonIdx ? { ...t, ...patch } : t)),
    )
  }

  const getMaxCarry = (track, level) => {
    return GAG_MAX_CARRY[track]?.[level] || 15
  }

  const updateGagCount = (track, level, delta) => {
    const curGags = { ...(currentToon.gags || {}) }
    const trackGags = { ...(curGags[track] || {}) }
    const currentCount = Number(trackGags[level]) || 0
    const maxCarry = getMaxCarry(track, level)

    if (delta > 0) {
      if (currentCount >= maxCarry) {
        setFeedback(`Maximum carry limit (${maxCarry}) reached for ${TRACK_LABELS[track]} Lvl ${level}!`)
        return
      }
      if (currentPouchCount >= 80) {
        setFeedback('Pouch capacity reached (80 gags max)!')
        return
      }
    }

    const nextCount = Math.max(0, currentCount + delta)
    if (nextCount === 0) {
      delete trackGags[level]
      if (Object.keys(trackGags).length === 0) {
        delete curGags[track]
      } else {
        curGags[track] = trackGags
      }
    } else {
      trackGags[level] = nextCount
      curGags[track] = trackGags
    }
    updateCurrentToon({ gags: curGags })
    setFeedback(null)
  }

  // Randomize active toon
  const handleRandomizeToon = async () => {
    try {
      setGenerating(true)
      const res = await randomToon()
      const toonData = res?.toon || res
      if (toonData) {
        let g = {}
        if (Array.isArray(toonData.gags)) {
          for (const item of toonData.gags) {
            if (Array.isArray(item) && item.length >= 3) {
              const [track, lvl, cnt] = item
              if (!g[track]) g[track] = {}
              g[track][lvl] = cnt
            }
          }
        } else if (toonData.gags && typeof toonData.gags === 'object') {
          g = toonData.gags
        }
        const org = Array.isArray(toonData.organic) ? toonData.organic[0] : toonData.organic
        updateCurrentToon({
          laff: toonData.laff,
          max_laff: toonData.max_laff || toonData.laff,
          organic: org || null,
          fires: toonData.fires || 0,
          unites_held: Array.isArray(toonData.unites_held) ? toonData.unites_held : [],
          sos_cards: Array.isArray(toonData.sos_cards) ? toonData.sos_cards : (typeof toonData.sos_cards === 'object' ? Object.keys(toonData.sos_cards) : []),
          gags: g,
        })
        setFeedback(`Randomized Toon ${activeToonIdx + 1}!`)
      }
    } catch (err) {
      setFeedback(`Error randomizing toon: ${err.message}`)
    } finally {
      setGenerating(false)
    }
  }

  // Handlers for Cogs
  const handleAddCog = () => {
    if (cogs.length >= 4) return
    const newCog = {
      dept: 'cashbot',
      name: 'Money Bags',
      level: 10,
      hp: 132,
      max_hp: 132,
      lured: false,
      lure_rounds: 2,
      trapped: false,
      trap_level: 6,
      suited: false,
    }
    setCogs([...cogs, newCog])
  }

  const handleRemoveCog = (idx) => {
    if (cogs.length <= 1) return
    setCogs(cogs.filter((_, i) => i !== idx))
  }

  const updateCog = (idx, patch) => {
    setCogs((list) =>
      list.map((c, i) => {
        if (i !== idx) return c
        const updated = { ...c, ...patch }
        // If level changed, recalculate default max HP unless user specifically patched hp
        if (patch.level && patch.hp === undefined) {
          const mhp = cogMaxHp(patch.level)
          updated.max_hp = mhp
          updated.hp = mhp
        }
        return updated
      }),
    )
  }

  // Preset Scenario Generator Trigger
  const handleScenarioPreset = async (kind) => {
    try {
      setGenerating(true)
      setFeedback(`Generating ${kind} scenario…`)
      const res = await generateScenario(kind)
      const st = res?.state || res
      const rawToons = st?.toons?.length ? st.toons : (st?.toon ? [st.toon] : [])

      if (rawToons.length) {
        const normalizedToons = rawToons.map((t) => {
          let g = {}
          if (Array.isArray(t.gags)) {
            for (const item of t.gags) {
              if (Array.isArray(item) && item.length >= 3) {
                const [track, lvl, cnt] = item
                if (!g[track]) g[track] = {}
                g[track][lvl] = cnt
              }
            }
          } else if (t.gags && typeof t.gags === 'object') {
            g = t.gags
          }
          const org = Array.isArray(t.organic) ? t.organic[0] : t.organic
          return {
            laff: t.laff,
            max_laff: t.max_laff || t.laff || 100,
            organic: org || null,
            fires: t.fires || 0,
            unites_held: Array.isArray(t.unites_held) ? t.unites_held : [],
            sos_cards: Array.isArray(t.sos_cards) ? t.sos_cards : (typeof t.sos_cards === 'object' ? Object.keys(t.sos_cards) : []),
            gags: g,
          }
        })
        setToons(normalizedToons)
      }

      const rawCogs = st?.cogs || []
      if (rawCogs.length) {
        setCogs(
          rawCogs.map((c) => ({
            dept: c.department || c.dept || 'sellbot',
            name: c.type || c.name || 'Cold Caller',
            level: c.level || 5,
            hp: c.hp != null ? c.hp : cogMaxHp(c.level || 5),
            max_hp: c.max_hp != null ? c.max_hp : cogMaxHp(c.level || 5),
            lured: Boolean(c.lured),
            lure_rounds: c.lure_rounds || 2,
            trapped: Boolean(c.trapped),
            trap_level: c.trap_level || 6,
            suited: Boolean(c.suited),
          })),
        )
      }
      setActiveToonIdx(0)
      setFeedback(`Loaded ${kind} scenario preset!`)
    } catch (err) {
      setFeedback(`Error: ${err.message}`)
    } finally {
      setGenerating(false)
    }
  }

  // Apply configuration and build tree
  const handleApply = () => {
    // Validate trapped cogs have trap_level
    for (let i = 0; i < cogs.length; i++) {
      if (cogs[i].trapped && !cogs[i].trap_level) {
        setFeedback(`Cog ${i + 1} is trapped but missing a Trap Level!`)
        return
      }
    }

    onApply({
      toons,
      cogs,
    })
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4 overflow-y-auto">
      <div className="bg-[#FBF9F5] border-2 border-amber-900/20 rounded-2xl shadow-2xl max-w-4xl w-full max-h-[90vh] flex flex-col overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* MODAL HEADER */}
        <div className="flex items-center justify-between px-4 py-3 border-b-2 border-amber-900/10 bg-[#F4F1EA]">
          <div>
            <h2 className="text-base font-black text-amber-950 flex items-center gap-2">
              ⚙️ Scenario Builder & Party Roster
            </h2>
            <p className="text-[11px] font-bold text-amber-900/60">
              Configure 1–4 toons, gag pouches, consumables, and cog board statuses
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleApply}
              disabled={busy || generating}
              className="btn btn-sm bg-emerald-500 hover:bg-emerald-600 text-white font-black text-xs rounded-xl toontown-btn-3d border border-emerald-700 px-3 cursor-pointer shadow-xs"
            >
              {busy ? 'Simulating…' : '⚔️ Update Battle Tree'}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="btn btn-sm bg-white hover:bg-amber-100 text-amber-950 font-black text-xs rounded-xl toontown-btn-3d border border-amber-900/20 cursor-pointer"
            >
              ✕ Close
            </button>
          </div>
        </div>

        {/* NOTIFICATION FEEDBACK BAR */}
        {feedback && (
          <div className="px-4 py-1.5 bg-amber-100/80 border-b border-amber-900/15 text-amber-950 font-extrabold text-[11px] flex items-center justify-between">
            <span>{feedback}</span>
            <button
              type="button"
              onClick={() => setFeedback(null)}
              className="text-amber-900/60 hover:text-amber-950 cursor-pointer text-xs"
            >
              ✕
            </button>
          </div>
        )}

        {/* SCENARIO GENERATOR PRESETS BAR */}
        <div className="px-4 py-2 border-b border-amber-900/10 bg-white flex items-center justify-between gap-2 flex-wrap">
          <span className="text-[10px] font-black uppercase tracking-wider text-amber-900/60">
            Scenario Presets:
          </span>
          <div className="flex items-center gap-1.5 flex-wrap">
            <button
              type="button"
              onClick={() => handleScenarioPreset('building')}
              disabled={generating}
              className="btn btn-xs h-[24px] min-h-0 bg-amber-50 hover:bg-amber-100 text-amber-950 font-black text-[10px] border border-amber-900/20 rounded-lg toontown-btn-3d cursor-pointer"
            >
              🏢 Cog Building
            </button>
            <button
              type="button"
              onClick={() => handleScenarioPreset('scrappy')}
              disabled={generating}
              className="btn btn-xs h-[24px] min-h-0 bg-amber-50 hover:bg-amber-100 text-amber-950 font-black text-[10px] border border-amber-900/20 rounded-lg toontown-btn-3d cursor-pointer"
            >
              🥊 Scrappy Fight
            </button>
            <button
              type="button"
              onClick={() => handleScenarioPreset('strange')}
              disabled={generating}
              className="btn btn-xs h-[24px] min-h-0 bg-amber-50 hover:bg-amber-100 text-amber-950 font-black text-[10px] border border-amber-900/20 rounded-lg toontown-btn-3d cursor-pointer"
            >
              🌀 Weird Mid-Battle
            </button>
            <button
              type="button"
              onClick={() => handleScenarioPreset('hard')}
              disabled={generating}
              className="btn btn-xs h-[24px] min-h-0 bg-amber-50 hover:bg-amber-100 text-amber-950 font-black text-[10px] border border-amber-900/20 rounded-lg toontown-btn-3d cursor-pointer"
            >
              🧱 Wall of Cogs
            </button>
            <button
              type="button"
              onClick={() => handleScenarioPreset('combo')}
              disabled={generating}
              className="btn btn-xs h-[24px] min-h-0 bg-amber-50 hover:bg-amber-100 text-amber-950 font-black text-[10px] border border-amber-900/20 rounded-lg toontown-btn-3d cursor-pointer"
            >
              🪤 Combo Setup
            </button>
          </div>
        </div>

        {/* MODAL MAIN BODY (Scrollable) */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* SECTION 1: TOON PARTY TABS & BUILDER */}
          <div className="space-y-3 rounded-2xl border-2 border-amber-900/15 bg-white p-3.5 shadow-xs">
            <div className="flex items-center justify-between border-b border-amber-900/10 pb-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-black text-amber-950 uppercase tracking-wider">
                  Toon Party ({toons.length}/4)
                </span>

                {/* Toon tabs */}
                <div className="flex items-center gap-1">
                  {toons.map((_, i) => (
                    <button
                      key={i}
                      type="button"
                      onClick={() => setActiveToonIdx(i)}
                      className={`px-2.5 py-1 text-[11px] font-black rounded-lg transition-all cursor-pointer border ${
                        activeToonIdx === i
                          ? 'bg-sky-500 text-white border-sky-600 shadow-xs'
                          : 'bg-amber-50 text-amber-950 border-amber-900/15 hover:bg-amber-100'
                      }`}
                    >
                      Toon {i + 1}
                    </button>
                  ))}
                  {toons.length < 4 && (
                    <button
                      type="button"
                      onClick={handleAddToon}
                      className="px-2 py-1 text-[11px] font-black rounded-lg bg-emerald-100 text-emerald-950 border border-emerald-400 hover:bg-emerald-200 cursor-pointer"
                      title="Add another Toon to the party"
                    >
                      + Add Toon
                    </button>
                  )}
                </div>
              </div>

              <div className="flex items-center gap-2">
                {toons.length > 1 && (
                  <button
                    type="button"
                    onClick={() => handleRemoveToon(activeToonIdx)}
                    className="btn btn-xs h-[22px] min-h-0 bg-rose-50 hover:bg-rose-100 text-rose-900 border border-rose-300 font-bold text-[9.5px] rounded-lg cursor-pointer"
                  >
                    Remove Toon {activeToonIdx + 1}
                  </button>
                )}
                <button
                  type="button"
                  onClick={handleRandomizeToon}
                  disabled={generating}
                  className="btn btn-xs h-[24px] min-h-0 bg-amber-400 hover:bg-amber-500 text-amber-950 font-black text-[10.5px] rounded-lg toontown-btn-3d border border-amber-600 shadow-2xs cursor-pointer"
                >
                  🎲 Randomize Toon
                </button>
              </div>
            </div>

            {/* Active Toon Attributes: Laff, Organic Track, Consumables */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3 text-amber-950">
              {/* Laff Controls */}
              <div className="space-y-1 bg-amber-50/50 p-2 rounded-xl border border-amber-900/10">
                <label className="text-[9.5px] font-black uppercase tracking-wider text-amber-900/60 block">
                  Laff Meter
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    min="1"
                    max={currentToon.max_laff || 137}
                    value={currentToon.laff != null ? currentToon.laff : 100}
                    onChange={(e) => updateCurrentToon({ laff: Number(e.target.value) })}
                    className="input input-xs w-16 bg-white font-mono font-black text-xs border border-amber-900/20 rounded-lg text-center"
                  />
                  <span className="text-xs font-bold text-amber-900/60">/</span>
                  <input
                    type="number"
                    min="15"
                    max="140"
                    value={currentToon.max_laff || 100}
                    onChange={(e) => updateCurrentToon({ max_laff: Number(e.target.value) })}
                    className="input input-xs w-16 bg-white font-mono font-black text-xs border border-amber-900/20 rounded-lg text-center"
                  />
                  <span className="text-[10px] font-bold">HP</span>
                </div>
              </div>

              {/* Organic Track Selector */}
              <div className="space-y-1 bg-amber-50/50 p-2 rounded-xl border border-amber-900/10">
                <label className="text-[9.5px] font-black uppercase tracking-wider text-amber-900/60 block">
                  Organic Track
                </label>
                <select
                  value={currentToon.organic || ''}
                  onChange={(e) => updateCurrentToon({ organic: e.target.value || null })}
                  className="select select-xs w-full bg-white font-extrabold text-[11px] border border-amber-900/20 rounded-lg"
                >
                  <option value="">None</option>
                  {TRACKS.map((t) => (
                    <option key={t} value={t}>
                      🍃 {TRACK_LABELS[t]}
                    </option>
                  ))}
                </select>
              </div>

              {/* Pink Slips (Fires) */}
              <div className="space-y-1 bg-amber-50/50 p-2 rounded-xl border border-amber-900/10">
                <label className="text-[9.5px] font-black uppercase tracking-wider text-amber-900/60 flex items-center gap-1">
                  <PinkSlip size="size-3.5" /> Pink Slips
                </label>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() =>
                      updateCurrentToon({ fires: Math.max(0, (currentToon.fires || 0) - 1) })
                    }
                    className="btn btn-xs size-6 min-h-0 bg-white border border-amber-900/20 rounded font-black text-xs cursor-pointer"
                  >
                    -
                  </button>
                  <span className="font-mono font-black text-xs w-8 text-center">
                    {currentToon.fires || 0}
                  </span>
                  <button
                    type="button"
                    onClick={() =>
                      updateCurrentToon({ fires: Math.min(10, (currentToon.fires || 0) + 1) })
                    }
                    className="btn btn-xs size-6 min-h-0 bg-white border border-amber-900/20 rounded font-black text-xs cursor-pointer"
                  >
                    +
                  </button>
                </div>
              </div>

              {/* Consumables Summary */}
              <div className="space-y-1 bg-amber-50/50 p-2 rounded-xl border border-amber-900/10">
                <label className="text-[9.5px] font-black uppercase tracking-wider text-amber-900/60 block">
                  Consumables Count
                </label>
                <div className="flex items-center gap-2 pt-0.5 text-[11px] font-black">
                  <div className="flex items-center gap-1" title="Unites held">
                    <UniteFist size="size-4" />
                    <span>{(currentToon.unites_held || []).length}</span>
                  </div>
                  <div className="flex items-center gap-1" title="SOS cards held">
                    <SosCard size="size-4" />
                    <span>{(currentToon.sos_cards || []).length}</span>
                  </div>
                  <span className="text-[9.5px] font-bold text-amber-900/60 ml-auto">
                    {currentPouchCount}/80 Gags
                  </span>
                </div>
              </div>
            </div>

            {/* 7-TRACK GAG POUCH GRID */}
            <div className="space-y-1.5 pt-1">
              <div className="flex items-center justify-between text-[10.5px] font-black text-amber-900/80 uppercase tracking-wider">
                <span>Gag Pouch Matrix (Toon {activeToonIdx + 1})</span>
                <span className="font-mono text-xs font-black text-sky-700">
                  Total: {currentPouchCount} / 80
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-7 gap-1.5">
                {TRACKS.map((track) => {
                  const isOrganic = currentToon.organic === track
                  const trackGags = currentToon.gags?.[track] || {}

                  return (
                    <div
                      key={track}
                      className={`track-${track} rounded-xl border p-2 space-y-1.5 bg-white/70 shadow-2xs`}
                    >
                      <div className="flex items-center justify-between">
                        <span
                          className="text-[10px] font-black uppercase tracking-tight truncate"
                          style={{ color: 'var(--track-text)' }}
                        >
                          {TRACK_LABELS[track]}
                        </span>
                        {isOrganic && <OrganicLeaf />}
                      </div>

                      {/* Gag Levels 1 to 7 */}
                      <div className="space-y-1">
                        {[1, 2, 3, 4, 5, 6, 7].map((lvl) => {
                          const count = Number(trackGags[lvl]) || 0
                          const maxCarry = getMaxCarry(track, lvl)
                          return (
                            <div
                              key={lvl}
                              className="flex items-center justify-between text-[10px] font-black bg-white/90 p-1 rounded border border-amber-900/10"
                            >
                              <div className="flex items-center gap-1">
                                <GagIcon track={track} level={lvl} size="size-4.5" />
                                <span className="font-mono text-[9px] text-amber-900/60">L{lvl}</span>
                              </div>

                              <div className="flex items-center gap-0.5">
                                <button
                                  type="button"
                                  onClick={() => updateGagCount(track, lvl, -1)}
                                  disabled={count === 0}
                                  className="size-4 rounded bg-amber-100 hover:bg-amber-200 text-amber-950 font-black text-[9px] flex items-center justify-center cursor-pointer disabled:opacity-30"
                                >
                                  -
                                </button>
                                <span
                                  className="font-mono text-[9.5px] w-6 text-center"
                                  title={`Holding ${count} of max ${maxCarry}`}
                                >
                                  {count}
                                </span>
                                <button
                                  type="button"
                                  onClick={() => updateGagCount(track, lvl, 1)}
                                  disabled={count >= maxCarry || currentPouchCount >= 80}
                                  title={count >= maxCarry ? `Max carry limit (${maxCarry})` : 'Add gag'}
                                  className="size-4 rounded bg-amber-100 hover:bg-amber-200 text-amber-950 font-black text-[9px] flex items-center justify-center cursor-pointer disabled:opacity-30"
                                >
                                  +
                                </button>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>

          {/* SECTION 2: COG LINEUP & STATUS CONTROLS */}
          <div className="space-y-3 rounded-2xl border-2 border-amber-900/15 bg-white p-3.5 shadow-xs">
            <div className="flex items-center justify-between border-b border-amber-900/10 pb-2">
              <div>
                <span className="text-xs font-black text-amber-950 uppercase tracking-wider">
                  Cog Roster ({cogs.length}/4)
                </span>
                <p className="text-[10px] font-bold text-amber-900/60">
                  Set Cog Level, HP, and statuses (Lured, Trapped, and Version 2.0 Suited)
                </p>
              </div>

              {cogs.length < 4 && (
                <button
                  type="button"
                  onClick={handleAddCog}
                  className="btn btn-xs h-[24px] min-h-0 bg-emerald-500 hover:bg-emerald-600 text-white font-black text-[10px] rounded-lg toontown-btn-3d border border-emerald-700 cursor-pointer"
                >
                  + Add Cog
                </button>
              )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {cogs.map((cog, idx) => (
                <div
                  key={idx}
                  className="rounded-xl border-2 border-amber-900/15 bg-[#FBF9F5] p-3 space-y-2.5 shadow-2xs"
                >
                  {/* Row Header: Dept, Cog Name, Level, Remove */}
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-1.5 flex-1 min-w-0">
                      <span className="size-5 rounded-full bg-amber-200 text-amber-950 flex items-center justify-center text-[10px] font-black shrink-0">
                        {idx + 1}
                      </span>

                      {/* Department Select */}
                      <select
                        value={cog.dept}
                        onChange={(e) => updateCog(idx, { dept: e.target.value })}
                        className="select select-xs bg-white font-extrabold text-[10.5px] border border-amber-900/20 rounded-lg capitalize w-24 shrink-0"
                      >
                        <option value="bossbot">Bossbot</option>
                        <option value="lawbot">Lawbot</option>
                        <option value="cashbot">Cashbot</option>
                        <option value="sellbot">Sellbot</option>
                      </select>

                      {/* Cog Name Input */}
                      <input
                        type="text"
                        value={cog.name}
                        onChange={(e) => updateCog(idx, { name: e.target.value })}
                        placeholder="Cog Name"
                        className="input input-xs flex-1 bg-white font-black text-[11px] border border-amber-900/20 rounded-lg px-2"
                      />
                    </div>

                    {cogs.length > 1 && (
                      <button
                        type="button"
                        onClick={() => handleRemoveCog(idx)}
                        className="size-5 rounded bg-rose-100 hover:bg-rose-200 text-rose-800 text-[11px] font-black flex items-center justify-center cursor-pointer"
                        title="Remove Cog"
                      >
                        ✕
                      </button>
                    )}
                  </div>

                  {/* Level and HP Controls */}
                  <div className="grid grid-cols-3 gap-2 text-amber-950">
                    <div className="space-y-0.5">
                      <label className="text-[8.5px] font-black uppercase tracking-wider text-amber-900/60 block">
                        Level
                      </label>
                      <input
                        type="number"
                        min="1"
                        max="20"
                        value={cog.level}
                        onChange={(e) => updateCog(idx, { level: Number(e.target.value) })}
                        className="input input-xs w-full bg-white font-mono font-black text-xs border border-amber-900/20 rounded-lg text-center"
                      />
                    </div>

                    <div className="space-y-0.5">
                      <label className="text-[8.5px] font-black uppercase tracking-wider text-amber-900/60 block">
                        Current HP
                      </label>
                      <input
                        type="number"
                        min="0"
                        max={cog.max_hp}
                        value={cog.hp}
                        onChange={(e) => updateCog(idx, { hp: Number(e.target.value) })}
                        className="input input-xs w-full bg-white font-mono font-black text-xs border border-amber-900/20 rounded-lg text-center"
                      />
                    </div>

                    <div className="space-y-0.5">
                      <label className="text-[8.5px] font-black uppercase tracking-wider text-amber-900/60 block">
                        Max HP
                      </label>
                      <input
                        type="number"
                        min="1"
                        max="1000"
                        value={cog.max_hp}
                        onChange={(e) => updateCog(idx, { max_hp: Number(e.target.value) })}
                        className="input input-xs w-full bg-white font-mono font-black text-xs border border-amber-900/20 rounded-lg text-center"
                      />
                    </div>
                  </div>

                  {/* STATUS CONTROLS: Lured, Trapped, Suited */}
                  <div className="grid grid-cols-3 gap-2 pt-1 border-t border-amber-900/10">
                    {/* Lured Toggle */}
                    <div className="space-y-1">
                      <label className="flex items-center gap-1.5 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={cog.lured}
                          onChange={(e) => updateCog(idx, { lured: e.target.checked })}
                          className="checkbox checkbox-xs checkbox-primary rounded"
                        />
                        <span className="text-[10px] font-black text-amber-950">🧲 Lured</span>
                      </label>
                      {cog.lured && (
                        <div className="flex items-center gap-1">
                          <span className="text-[8.5px] font-bold text-amber-900/60">Rounds:</span>
                          <select
                            value={cog.lure_rounds || 2}
                            onChange={(e) => updateCog(idx, { lure_rounds: Number(e.target.value) })}
                            className="select select-xs h-5 min-h-0 text-[9.5px] font-black bg-white rounded p-0.5"
                          >
                            {[1, 2, 3, 4].map((r) => (
                              <option key={r} value={r}>
                                {r}
                              </option>
                            ))}
                          </select>
                        </div>
                      )}
                    </div>

                    {/* Trapped Toggle */}
                    <div className="space-y-1">
                      <label className="flex items-center gap-1.5 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={cog.trapped}
                          onChange={(e) => updateCog(idx, { trapped: e.target.checked })}
                          className="checkbox checkbox-xs checkbox-warning rounded"
                        />
                        <span className="text-[10px] font-black text-amber-950">🍌 Trapped</span>
                      </label>
                      {cog.trapped && (
                        <div className="space-y-0.5">
                          <select
                            value={cog.trap_level || 6}
                            onChange={(e) => updateCog(idx, { trap_level: Number(e.target.value) })}
                            className="select select-xs h-5 min-h-0 text-[8.5px] font-black bg-white rounded p-0.5 w-full"
                          >
                            {TRAP_NAMES.map((name, i) => (
                              <option key={i + 1} value={i + 1}>
                                {name}
                              </option>
                            ))}
                          </select>
                        </div>
                      )}
                    </div>

                    {/* Version 2.0 Suited Toggle */}
                    <div className="space-y-1">
                      <label className="flex items-center gap-1.5 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={cog.suited}
                          onChange={(e) => updateCog(idx, { suited: e.target.checked })}
                          className="checkbox checkbox-xs checkbox-secondary rounded"
                        />
                        <span className="text-[10px] font-black text-amber-950">⚙️ V2.0 Suited</span>
                      </label>
                      <span className="text-[8px] font-bold text-amber-900/50 block">
                        Skelecog under suit
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
