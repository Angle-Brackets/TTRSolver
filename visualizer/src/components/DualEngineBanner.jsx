import React from 'react'
import { GagIcon, PinkSlip, SosCard, UniteFist, OrganicLeaf } from './Icons'

export default function DualEngineBanner({
  engineMode,
  setEngineMode,
  preset,
  setPreset,
  presets,
  depth,
  setDepth,
  budget,
  setBudget,
  climbResult,
  bestLine,
  preferredEngine,
  setPreferredEngine,
  onShowBestPath,
  onCollapseAll,
  onFitView,
  onToggleSetup,
  showSetup,
  busy,
}) {
  const isBoth = engineMode === 'both'
  const isPpoActive = engineMode === 'ppo' || (isBoth && preferredEngine === 'rl')

  // Extract RL (climb) primary move
  const rlPlan = climbResult?.plan || []
  const rlFirst = climbResult?.first
  const rlAction = rlFirst?.action
  const rlTrack = rlFirst?.track || (rlAction ? rlAction.track : null)
  const rlLevel = rlFirst?.level || (rlAction ? rlAction.level : null)
  const rlLabel = rlFirst?.label || (climbResult?.labels ? climbResult.labels[0] : null)
  const rlUnite = climbResult?.unite

  // Extract Search best line primary move
  const searchFirst = bestLine && bestLine[0]
  const searchAction = searchFirst?.action
  const searchTrack = searchAction?.track
  const searchLevel = searchAction?.level
  const searchLabel = searchFirst?.label
  const searchEv = searchFirst?.ev

  // Choose which is primary and which is runner-up
  const primaryTrack = isPpoActive ? rlTrack : searchTrack
  const primaryLevel = isPpoActive ? rlLevel : searchLevel
  const primaryLabel = isPpoActive ? rlLabel : searchLabel
  const primaryEngineName = isPpoActive ? 'RL (PPO)' : 'SEARCH'

  const runnerTrack = isPpoActive ? searchTrack : rlTrack
  const runnerLevel = isPpoActive ? searchLevel : rlLevel
  const runnerLabel = isPpoActive ? searchLabel : rlLabel
  const runnerEngineName = isPpoActive ? 'SEARCH' : 'RL'
  const hasDisagreement = primaryLabel && runnerLabel && primaryLabel !== runnerLabel

  return (
    <div className="flex flex-col gap-2 p-2.5 bg-[#F4F1EA] border-b-2 border-amber-900/10 shadow-xs">
      {/* TOP CONTROL BAR */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        {/* Title & Engine Mode Segmented Button */}
        <div className="flex items-center gap-2.5 flex-wrap">
          <span className="font-black text-amber-950 text-[14.5px] tracking-tight">
            Cog Battle Tree Explorer
          </span>

          {/* Engine Selector: PPO / Search / Both */}
          <div className="flex items-center gap-1 bg-amber-900/10 p-0.5 rounded-xl border border-amber-900/15 shadow-inner">
            <button
              type="button"
              onClick={() => setEngineMode('ppo')}
              className={`px-2.5 py-1 text-[10.5px] font-black rounded-lg transition-all cursor-pointer ${engineMode === 'ppo'
                  ? 'bg-emerald-500 text-white shadow-xs border border-emerald-600'
                  : 'text-amber-950 opacity-70 hover:opacity-100 hover:bg-white/40'
                }`}
              title="Show only PPO policy recommendations"
            >
              PPO (RL)
            </button>
            <button
              type="button"
              onClick={() => setEngineMode('search')}
              className={`px-2.5 py-1 text-[10.5px] font-black rounded-lg transition-all cursor-pointer ${engineMode === 'search'
                  ? 'bg-sky-500 text-white shadow-xs border border-sky-600'
                  : 'text-amber-950 opacity-70 hover:opacity-100 hover:bg-white/40'
                }`}
              title="Show only Expectimax search recommendations"
            >
              Search
            </button>
            <button
              type="button"
              onClick={() => setEngineMode('both')}
              className={`px-2.5 py-1 text-[10.5px] font-black rounded-lg transition-all cursor-pointer ${engineMode === 'both'
                  ? 'bg-amber-500 text-white shadow-xs border border-amber-600'
                  : 'text-amber-950 opacity-70 hover:opacity-100 hover:bg-white/40'
                }`}
              title="Compare both engines side-by-side with dual path coloring"
            >
              Both (Compare)
            </button>
          </div>
        </div>

        {/* Solver Knobs: Preset, Depth, Budget */}
        <div className="flex items-center gap-2 flex-wrap text-amber-950">
          {/* Preset Selector */}
          <div className="flex items-center gap-1">
            <label className="text-[9px] font-black uppercase tracking-wider text-amber-900/60">Preset</label>
            <select
              value={preset}
              onChange={(e) => setPreset(e.target.value)}
              className="select select-xs h-[26px] min-h-0 bg-white font-extrabold text-[11px] text-amber-950 border border-amber-900/20 rounded-lg cursor-pointer px-1.5 focus:outline-none"
            >
              {(presets || []).map((p) => (
                <option key={p.name} value={p.name} title={p.description}>
                  {p.name.charAt(0).toUpperCase() + p.name.slice(1)}
                </option>
              ))}
            </select>
          </div>

          {/* Depth Selector */}
          <div className="flex items-center gap-1">
            <label className="text-[9px] font-black uppercase tracking-wider text-amber-900/60">Depth</label>
            <select
              value={depth}
              onChange={(e) => setDepth(Number(e.target.value))}
              className="select select-xs h-[26px] min-h-0 bg-white font-extrabold text-[11px] text-amber-950 border border-amber-900/20 rounded-lg cursor-pointer px-1.5 focus:outline-none"
            >
              {[1, 2, 3, 4].map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </div>

          {/* Think Time Slider */}
          <div className="flex items-center gap-1.5 bg-white px-2 py-0.5 rounded-lg border border-amber-900/15">
            <label className="text-[9px] font-black uppercase tracking-wider text-amber-900/60">Think</label>
            <input
              type="range"
              min="3"
              max="45"
              step="1"
              value={budget}
              onChange={(e) => setBudget(Number(e.target.value))}
              className="range range-xs range-primary w-16 cursor-pointer accent-sky-500"
            />
            <span className="font-mono text-[10px] font-black text-sky-700 w-5 text-right">{budget}s</span>
          </div>

          {/* Actions: Show Best Path, Collapse, Fit, Setup */}
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={onShowBestPath}
              disabled={busy}
              className="btn btn-xs h-[28px] min-h-0 bg-amber-400 hover:bg-amber-500 border border-amber-600 text-amber-950 font-black text-[11px] rounded-lg toontown-btn-3d cursor-pointer shadow-xs disabled:opacity-40"
            >
              {busy ? 'Searching…' : '⭐ Show Best Path'}
            </button>
            <button
              type="button"
              onClick={onCollapseAll}
              className="btn btn-xs h-[28px] min-h-0 bg-white hover:bg-amber-100 border border-amber-900/20 text-amber-950 font-black text-[11px] rounded-lg toontown-btn-3d cursor-pointer"
            >
              Collapse
            </button>
            <button
              type="button"
              onClick={onFitView}
              className="btn btn-xs h-[28px] min-h-0 bg-white hover:bg-amber-100 border border-amber-900/20 text-amber-950 font-black text-[11px] rounded-lg toontown-btn-3d cursor-pointer"
            >
              Fit
            </button>
            <button
              type="button"
              onClick={onToggleSetup}
              className={`btn btn-xs h-[28px] min-h-0 font-black text-[11px] rounded-lg toontown-btn-3d cursor-pointer border ${showSetup
                  ? 'bg-sky-500 text-white border-sky-700'
                  : 'bg-white hover:bg-amber-100 text-amber-950 border-amber-900/20'
                }`}
            >
              {showSetup ? 'Hide Setup' : '⚙️ Setup'}
            </button>
          </div>
        </div>
      </div>

      {/* DUAL-ENGINE ADVICE HERO & RUNNER-UP CARDS */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-3 flex-1 min-w-0">
          {/* Instant Unite Alert */}
          {rlUnite && (
            <div className="flex items-center gap-1.5 rounded-xl border-2 border-emerald-500 bg-emerald-50 px-2 py-1 text-emerald-950 shadow-xs animate-pulse">
              <UniteFist size="size-4" />
              <div className="text-[10px] font-black uppercase text-emerald-800">
                UNITE FIRST: {rlUnite[0]} ({rlUnite[1]})
              </div>
            </div>
          )}

          {/* Primary Recommendation Hero Card */}
          <div
            className={`track-${primaryTrack || 'none'} toontown-card-hero flex items-center gap-2.5 rounded-xl px-3 py-1.5 min-w-[260px] max-w-[420px] transition-all`}
          >
            {primaryTrack && primaryLevel ? (
              <GagIcon track={primaryTrack} level={primaryLevel} size="size-9" />
            ) : primaryTrack === 'fire' ? (
              <PinkSlip size="size-8" />
            ) : primaryTrack === 'sos' ? (
              <SosCard size="size-8" />
            ) : null}

            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5">
                <span
                  className="text-[9px] font-black uppercase tracking-wider"
                  style={{ color: 'var(--track-text)' }}
                >
                  {primaryEngineName}
                </span>
                {primaryTrack && primaryLevel && (
                  <span className="rounded-full bg-white/90 px-1.5 py-0.2 text-[8.5px] font-black text-amber-950 border border-amber-900/15">
                    LVL {primaryLevel}
                  </span>
                )}
                {searchEv != null && !isPpoActive && (
                  <span className="bg-sky-100 text-sky-950 border border-sky-300 rounded px-1 text-[8.5px] font-black">
                    EV {searchEv > 0 ? `+${searchEv.toFixed(1)}` : searchEv.toFixed(1)}
                  </span>
                )}
              </div>
              <div className="text-[13px] font-black text-amber-950 truncate">
                {primaryLabel || (busy ? 'Computing best line…' : 'Awaiting position')}
              </div>
            </div>
          </div>

          {/* Runner-Up Engine Disagreement Card */}
          {hasDisagreement && (
            <div className="flex items-center gap-2 rounded-xl border-2 border-amber-900/15 bg-white/90 px-2.5 py-1.5 shadow-xs">
              <span
                className={`badge badge-xs px-1.5 text-[8px] font-black uppercase tracking-wider text-white ${isPpoActive ? 'bg-sky-600 border-sky-700' : 'bg-emerald-600 border-emerald-700'
                  }`}
              >
                {runnerEngineName}
              </span>

              {runnerTrack && runnerLevel && (
                <GagIcon track={runnerTrack} level={runnerLevel} size="size-6" />
              )}

              <span className="text-[11px] font-black text-amber-950 truncate max-w-[140px]">
                {runnerLabel}
              </span>

              <button
                type="button"
                onClick={() => setPreferredEngine(isPpoActive ? 'search' : 'rl')}
                className="btn btn-xs h-[22px] min-h-0 bg-amber-50 hover:bg-amber-100 border border-amber-900/20 text-amber-950 font-black text-[9px] toontown-btn-3d px-1.5 cursor-pointer"
                title={`Swap primary view to ${runnerEngineName}`}
              >
                Use Move ➔
              </button>
            </div>
          )}
        </div>

        {/* Legend in Both Mode */}
        {isBoth && (
          <div className="flex items-center gap-3 text-[10px] font-black bg-white/80 px-2.5 py-1 rounded-xl border border-amber-900/10">
            <span className="text-amber-900/60 uppercase text-[8.5px]">Path Legend:</span>
            <div className="flex items-center gap-1">
              <span className="inline-block w-3 h-1 bg-emerald-500 rounded-full" />
              <span className="text-emerald-800">PPO (RL)</span>
            </div>
            <div className="flex items-center gap-1">
              <span className="inline-block w-3 h-1 bg-sky-500 rounded-full" />
              <span className="text-sky-800">Search</span>
            </div>
            <div className="flex items-center gap-1">
              <span className="inline-block w-3 h-1 bg-amber-400 rounded-full" />
              <span className="text-amber-800">Both Agree</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
