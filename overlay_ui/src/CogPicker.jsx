import React, { useEffect, useRef, useState } from 'react'

/**
 * Naming a cog, without a native <select>.
 * Rendered in the page's own DOM, styled in Toontown light theme.
 * Includes quick search filter box for easy selection.
 */
export default function CogPicker({ row, onPick }) {
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('')
  const box = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    if (!open) {
      setFilter('')
      return undefined
    }
    const away = (e) => {
      if (box.current && !box.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [open])

  useEffect(() => {
    if (open && inputRef.current) {
      inputRef.current.focus()
    }
  }, [open])

  const choices = row.choices ?? []
  const current = choices.find((c) => c.current)

  const query = filter.toLowerCase().trim()
  const filtered = query
    ? choices.filter((c) => c.display.toLowerCase().includes(query) || (c.department && c.department.toLowerCase().includes(query)))
    : choices

  const likely = filtered.filter((c) => c.likely)
  const rest = filtered.filter((c) => !c.likely)

  const pick = (key) => {
    setOpen(false)
    setFilter('')
    onPick(key)
  }

  const Item = ({ c }) => (
    <button
      type="button"
      className={`w-full px-2 py-1 text-left text-[11.5px] font-medium transition-colors hover:bg-sky-100 hover:text-sky-900 rounded-md ${
        c.current ? 'font-black text-sky-700 bg-sky-50' : 'text-slate-700'
      }`}
      onClick={() => pick(c.key)}
    >
      {c.display}
    </button>
  )

  return (
    <div ref={box} className="min-w-0 flex-1 max-w-[105px] shrink-0 relative">
      <button
        type="button"
        className={`w-full truncate rounded-lg px-1.5 py-0.5 text-left text-[11.5px] font-extrabold tracking-wide border border-amber-900/10 hover:bg-amber-100/50 transition-all cursor-pointer ${
          row.identified ? 'text-amber-950 opacity-90' : 'italic text-amber-900/60 opacity-80'
        }`}
        onClick={() => setOpen((v) => !v)}
        title={row.identified
          ? `Read as ${row.name} — click to correct it`
          : 'Unidentified — click to say which cog this is'}
      >
        {current ? current.display : (row.identified ? row.name : `${row.name}?`)}
      </button>

      {open && (
        <div className="mt-1 max-h-56 w-48 overflow-y-auto rounded-xl border-2 border-amber-900/20 bg-white shadow-xl z-50 p-1 space-y-1">
          <input
            ref={inputRef}
            type="text"
            placeholder="Search cog..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            onMouseDown={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
            className="w-full px-2 py-1 text-[11px] font-semibold border border-amber-900/15 rounded-lg bg-amber-50/50 focus:bg-white focus:outline-none focus:ring-1 focus:ring-sky-500"
          />
          {likely.length > 0 && (
            <>
              <div className="px-2 pt-0.5 text-[8.5px] font-black uppercase tracking-wider text-amber-700/70">
                Likely Match
              </div>
              {likely.map((c) => <Item key={c.key} c={c} />)}
              <div className="my-0.5 border-t border-amber-900/10" />
            </>
          )}
          <div className="px-2 pt-0.5 text-[8.5px] font-black uppercase tracking-wider text-slate-400">
            {query ? 'Matching Cogs' : 'All Cogs'}
          </div>
          {rest.map((c) => <Item key={c.key} c={c} />)}
          {filtered.length === 0 && (
            <div className="px-2 py-2 text-[11px] font-medium text-slate-400 italic text-center">
              No matching cogs
            </div>
          )}
        </div>
      )}
    </div>
  )
}
