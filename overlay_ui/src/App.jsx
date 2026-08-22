import React, { useEffect, useState } from 'react'

// The model Python posts. Shape matches `overlay.Model.to_json()`; this
// default is also what the page shows when opened in a browser with no
// Python behind it, so `npm run dev` is useful on its own.
const EMPTY = {
  in_battle: false, status: 'waiting', turn: 0,
  advice: '', track: null, rows: [], problems: [],
  evidence: '', can_confirm: false, can_advise: false, thinking: false,
}

function healthClass(h) {
  if (h > 0.6) return 'bg-success'
  if (h > 0.25) return 'bg-warning'
  return 'bg-error'
}

function CogRow({ row }) {
  return (
    <div className="flex items-center gap-2 py-[3px]">
      <span className="w-6 text-right font-mono text-[11px] opacity-40">
        {row.level ?? '?'}
      </span>
      <span
        className={`w-32 truncate text-[13px] ${
          row.identified ? 'opacity-70' : 'opacity-40 italic'
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
      <span className="w-9 text-right font-mono text-[11px] opacity-60">
        {Math.round(row.health * 100)}%
      </span>
    </div>
  )
}

function Advice({ model }) {
  const showing = Boolean(model.advice) && model.in_battle
  const track = showing && model.track ? model.track : 'none'
  return (
    <div
      className={`track-${track} relative overflow-hidden rounded-box bg-base-200 px-4 py-3`}
    >
      <div
        className="absolute inset-y-0 left-0 w-[3px]"
        style={{ background: 'var(--accent)' }}
      />
      {showing && model.track && (
        <div
          className="text-[10px] font-semibold tracking-[0.14em]"
          style={{ color: 'var(--accent)' }}
        >
          {model.track.replace('_', '-').toUpperCase()}
        </div>
      )}
      <div
        className={
          showing
            ? 'text-[19px] font-bold leading-tight'
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
  useEffect(() => {
    const send = () => {
      const h = document.getElementById('root')?.scrollHeight
      if (h && window.pywebview?.api?.set_height) {
        window.pywebview.api.set_height(Math.ceil(h))
      }
    }
    const id = requestAnimationFrame(send)
    return () => cancelAnimationFrame(id)
  }, [model])

  const call = (name) => {
    if (window.pywebview?.api?.[name]) window.pywebview.api[name]()
  }

  return (
    <div className="flex min-h-full flex-col gap-2 bg-base-100 p-4 text-base-content">
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

      <div className="mt-auto flex items-center gap-2 pt-1">
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
          ✕
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
