import React, { useState, useEffect } from 'react'
import { GagIcon, CogAvatar, DeptIcon, PinkSlip, SosCard, UniteFist, OrganicLeaf } from './Icons'
import { fetchCogForecast } from '../api'

function healthClass(ratio) {
  if (ratio > 0.6) return 'bg-emerald-500'
  if (ratio > 0.25) return 'bg-amber-500'
  return 'bg-rose-500'
}

export default function Inspector({
  node,
  engineMode,
  bestLine,
  climbResult,
  onExpand,
  onCollapse,
  busy,
}) {
  const [forecast, setForecast] = useState(null)
  const [forecastLoading, setForecastLoading] = useState(false)
  const [forecastError, setForecastError] = useState(null)

  const state = node?.state
  const toons = state?.toons || (state?.toon ? [state.toon] : [])
  const cogs = state?.cogs || []
  const isTerminal = node?.kind === 'terminal'
  const isAction = node?.kind === 'action'

  // Fetch cog forecast when selected node state changes
  useEffect(() => {
    if (!state || isTerminal || !cogs.length) {
      setForecast(null)
      return
    }
    let cancelled = false
    setForecastLoading(true)
    setForecastError(null)

    fetchCogForecast(state)
      .then((res) => {
        if (!cancelled) {
          setForecast(res?.cogs || [])
          setForecastLoading(false)
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setForecastError(err.message)
          setForecastLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [node?.id, state, isTerminal, cogs.length])

  if (!node) {
    return (
      <aside className="w-80 border-l-2 border-amber-900/10 bg-[#FBF9F5] p-3 flex flex-col items-center justify-center text-center text-amber-900/50">
        <p className="text-xs font-black">Select any node in the tree to inspect details</p>
      </aside>
    )
  }

  const hasChildren = Boolean(node.children && node.children.length > 0)
  const isOpen = Boolean(node.open)

  return (
    <aside className="w-84 border-l-2 border-amber-900/10 bg-[#FBF9F5] flex flex-col h-full shadow-inner overflow-y-auto">
      {/* HEADER: Node Title, Type & Actions */}
      <div className="p-3 border-b border-amber-900/10 bg-white/60 space-y-2 sticky top-0 z-10 backdrop-blur-xs">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <span className="text-[10px] font-black uppercase tracking-wider text-amber-900/60">
              {isTerminal ? 'Terminal' : isAction ? 'Action Choice' : 'Turn Position'}
            </span>
            {node.turn != null && (
              <span className="rounded bg-amber-100 px-1 py-0.2 text-[9px] font-black text-amber-900 border border-amber-900/15">
                Turn {node.turn}
              </span>
            )}
          </div>

          {/* Non-emoji engine path badge */}
          {node.onBothPath ? (
            <span className="badge badge-xs bg-amber-500 text-white font-black text-[7.5px] px-1.5 border-amber-600 shadow-2xs">
              BOTH AGREE
            </span>
          ) : node.onPpoPath ? (
            <span className="badge badge-xs bg-emerald-600 text-white font-black text-[7.5px] px-1.5 border-emerald-700 shadow-2xs">
              RL CHOICE
            </span>
          ) : node.onSearchPath ? (
            <span className="badge badge-xs bg-sky-600 text-white font-black text-[7.5px] px-1.5 border-sky-700 shadow-2xs">
              SEARCH LINE
            </span>
          ) : null}
        </div>

        <div className="flex items-center gap-2">
          {isAction && node.action?.track && node.action?.level ? (
            <GagIcon track={node.action.track} level={node.action.level} size="size-7" />
          ) : null}
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-black text-amber-950 truncate">
              {node.label || 'Decision Node'}
            </div>
            <div className="flex items-center gap-2 text-[10px] font-bold text-amber-900/70">
              {node.ev != null && (
                <span>
                  EV:{' '}
                  <strong className="text-amber-950">
                    {node.ev > 0 ? `+${node.ev.toFixed(1)}` : node.ev.toFixed(1)}
                  </strong>
                </span>
              )}
              {node.prob != null && (
                <span>
                  Odds: <strong className="text-emerald-700">{(node.prob * 100).toFixed(1)}%</strong>
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Tree branch toggle button */}
        {!isTerminal && node.kind !== 'more' && (
          <div className="flex items-center gap-1.5 pt-1">
            {hasChildren ? (
              <button
                type="button"
                onClick={() => onCollapse(node)}
                disabled={busy}
                className="btn btn-xs flex-1 h-[24px] min-h-0 bg-white hover:bg-amber-100 border border-amber-900/20 text-amber-950 font-black text-[10px] rounded-lg toontown-btn-3d cursor-pointer"
              >
                {isOpen ? 'Collapse Subtree' : 'Expand Subtree'}
              </button>
            ) : (
              <button
                type="button"
                onClick={() => onExpand(node)}
                disabled={busy}
                className="btn btn-xs flex-1 h-[24px] min-h-0 bg-sky-500 hover:bg-sky-600 text-white font-black text-[10px] rounded-lg toontown-btn-3d cursor-pointer border border-sky-600 shadow-2xs"
              >
                {busy ? 'Expanding…' : 'Expand Moves (+)'}
              </button>
            )}
          </div>
        )}
      </div>

      {/* BODY CONTENT SECTIONS */}
      <div className="p-3 space-y-3.5">
        {/* TOON PARTY SECTION */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-[10.5px] font-black text-amber-900/80 uppercase tracking-wider">
            <span>Toon Party ({toons.length})</span>
          </div>

          <div className="space-y-1.5">
            {toons.map((toon, idx) => {
              const maxLaff = toon.max_laff || 137
              const laff = toon.laff != null ? toon.laff : maxLaff
              const laffRatio = Math.max(0, Math.min(1, laff / maxLaff))
              const organic = toon.organic
              const fires = toon.fires || 0
              const unites = (toon.unites_held || []).length
              const sos = (toon.sos_cards || []).length

              return (
                <div
                  key={idx}
                  className="rounded-xl border border-amber-900/15 bg-white p-2 shadow-xs space-y-1.5"
                >
                  <div className="flex items-center justify-between text-[11px] font-black text-amber-950">
                    <div className="flex items-center gap-1.5">
                      <span className="size-4 rounded-full bg-amber-200 text-amber-900 flex items-center justify-center text-[9px] font-black">
                        {idx + 1}
                      </span>
                      <span>Toon {idx + 1}</span>
                      {organic && <OrganicLeaf />}
                    </div>
                    <span className="font-mono text-[10px]">
                      {laff} / {maxLaff} Laff
                    </span>
                  </div>

                  {/* Laff Meter Bar */}
                  <div className="h-[6px] w-full overflow-hidden rounded-full bg-amber-900/10 border border-amber-900/10 p-[0.5px]">
                    <div
                      className={`h-full rounded-full transition-all duration-300 ${healthClass(laffRatio)}`}
                      style={{ width: `${Math.max(4, laffRatio * 100)}%` }}
                    />
                  </div>

                  {/* Consumables held */}
                  <div className="flex items-center gap-3 pt-0.5 text-[9.5px] font-black text-amber-900/75">
                    <div className="flex items-center gap-1" title={`${fires} Pink Slips held`}>
                      <PinkSlip size="size-3.5" />
                      <span>{fires}</span>
                    </div>
                    <div className="flex items-center gap-1" title={`${unites} Unites held`}>
                      <UniteFist size="size-3.5" />
                      <span>{unites}</span>
                    </div>
                    <div className="flex items-center gap-1" title={`${sos} SOS Cards held`}>
                      <SosCard size="size-3.5" />
                      <span>{sos}</span>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* COG ROSTER SECTION */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-[10.5px] font-black text-amber-900/80 uppercase tracking-wider">
            <span>Cog Lineup ({cogs.length})</span>
          </div>

          {cogs.length === 0 ? (
            <div className="rounded-xl border border-dashed border-amber-900/20 p-2.5 text-center text-[10px] font-black text-emerald-800 bg-emerald-50/50">
              No Cogs remaining! (Board cleared)
            </div>
          ) : (
            <div className="space-y-1.5">
              {cogs.map((cog, idx) => {
                const maxHp = cog.max_hp || 100
                const hp = cog.hp != null ? cog.hp : maxHp
                const hpRatio = Math.max(0, Math.min(1, hp / maxHp))
                const isDefeated = hp <= 0
                const isLured = Boolean(cog.lured)
                const isTrapped = Boolean(cog.trapped)
                const isSuited = Boolean(cog.suited)

                return (
                  <div
                    key={idx}
                    className={`rounded-xl border-2 p-2 transition-all shadow-xs space-y-1.5 ${
                      isDefeated
                        ? 'bg-amber-900/5 border-dashed border-amber-900/20 opacity-50'
                        : 'bg-white border-amber-900/15'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-1.5">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <CogAvatar department={cog.department || cog.dept} type={cog.type} size="size-6" />
                        <div className="min-w-0">
                          <div className="text-[11px] font-black text-amber-950 truncate">
                            {cog.name || `Cog ${idx + 1}`}
                          </div>
                          <div className="text-[9px] font-extrabold text-amber-900/60 uppercase">
                            Level {cog.level} {cog.department || cog.dept || ''}
                          </div>
                        </div>
                      </div>

                      <div className="text-right">
                        <span className="font-mono text-[9.5px] font-black text-amber-950">
                          {hp} / {maxHp} HP
                        </span>
                      </div>
                    </div>

                    {/* HP Bar */}
                    <div className="h-[6px] w-full overflow-hidden rounded-full bg-amber-900/10 border border-amber-900/10 p-[0.5px]">
                      <div
                        className={`h-full rounded-full transition-all duration-300 ${healthClass(hpRatio)}`}
                        style={{ width: `${Math.max(4, hpRatio * 100)}%` }}
                      />
                    </div>

                    {/* Status badges: Lured, Trapped, Suited */}
                    <div className="flex items-center gap-1 flex-wrap pt-0.5">
                      {isLured && (
                        <span className="rounded bg-emerald-100 text-emerald-950 border border-emerald-300 px-1.5 py-0.2 text-[8px] font-black uppercase">
                          🧲 Lured ({cog.lure_rounds || 1}r)
                        </span>
                      )}
                      {isTrapped && (
                        <span className="rounded bg-amber-100 text-amber-950 border border-amber-300 px-1.5 py-0.2 text-[8px] font-black uppercase">
                          🍌 Trapped (Lvl {cog.trap_level || '?'})
                        </span>
                      )}
                      {isSuited && (
                        <span className="rounded bg-purple-100 text-purple-950 border border-purple-300 px-1.5 py-0.2 text-[8px] font-black uppercase">
                          ⚙️ V2.0 Suited
                        </span>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* THREAT FORECAST SECTION (What the Cogs Do Next) */}
        {!isTerminal && cogs.length > 0 && (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-[10.5px] font-black text-amber-900/80 uppercase tracking-wider">
              <span>Cog Threat Forecast</span>
              {forecastLoading && <span className="loading loading-spinner loading-xs text-sky-600" />}
            </div>

            {forecastError && (
              <div className="rounded-xl border border-rose-300 bg-rose-50 p-2 text-[9.5px] font-black text-rose-800">
                Forecast unavailable: {forecastError}
              </div>
            )}

            {forecast && forecast.length > 0 && (
              <div className="space-y-1.5">
                {forecast.map((fc, i) => (
                  <div
                    key={i}
                    className="rounded-xl border border-amber-900/10 bg-white/90 p-2 shadow-2xs space-y-1 text-[10px]"
                  >
                    <div className="flex items-center justify-between font-black text-amber-950">
                      <span>{fc.name || `Cog ${i + 1}`}</span>
                      {fc.kills_toon && (
                        <span className="rounded bg-rose-100 text-rose-900 border border-rose-300 px-1 text-[8px] font-black animate-pulse">
                          💀 CAN KILL
                        </span>
                      )}
                    </div>

                    <div className="flex items-center justify-between text-amber-900/70 font-semibold text-[9.5px]">
                      <span>Target: {fc.target || 'Random Toon'}</span>
                      <span>
                        Dmg: {fc.threat_mean?.toFixed(0) || 0} (Max {fc.threat_max || 0})
                      </span>
                    </div>

                    {fc.attacks && fc.attacks.length > 0 && (
                      <div className="pt-0.5 space-y-0.5 border-t border-amber-900/10">
                        {fc.attacks.slice(0, 3).map((atk, ai) => (
                          <div
                            key={ai}
                            className="flex items-center justify-between text-[8.5px] font-mono text-amber-900/80"
                          >
                            <span className="truncate max-w-[130px]">{atk.name}</span>
                            <span>{Math.round((atk.prob || 0) * 100)}% ({atk.damage} dmg)</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* SOLVER'S PLAN FROM HERE SECTION */}
        {bestLine && bestLine.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-[10.5px] font-black text-amber-900/80 uppercase tracking-wider">
              <span>Expected Best Line</span>
            </div>

            <div className="space-y-1">
              {bestLine.map((step, idx) => (
                <div
                  key={idx}
                  className={`flex items-center justify-between rounded-xl border p-1.5 shadow-2xs text-[10px] ${
                    idx === 0
                      ? 'bg-amber-100/70 border-amber-400 font-black'
                      : 'bg-white border-amber-900/10 font-bold'
                  }`}
                >
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className="text-[9px] font-black text-amber-900/60 w-3">
                      {idx + 1}.
                    </span>
                    {step.action?.track && step.action?.level && (
                      <GagIcon track={step.action.track} level={step.action.level} size="size-5" />
                    )}
                    <span className="truncate text-amber-950">{step.label}</span>
                  </div>

                  {step.ev != null && (
                    <span className="font-mono text-[9px] text-amber-900/80 shrink-0">
                      EV {step.ev > 0 ? `+${step.ev.toFixed(0)}` : step.ev.toFixed(0)}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </aside>
  )
}
