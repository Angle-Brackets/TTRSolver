import React, { useEffect, useRef, useState } from 'react'

/**
 * Naming a cog, without a native <select>.
 *
 * WHY NOT A SELECT. The panel is a 430px frameless always-on-top
 * WebView2 window. A native select popup is an OS-level window that
 * escapes those bounds, and in that configuration the click lands on the
 * game behind rather than on the page -- the list opens, shows the right
 * cogs, and picking one does nothing. That is what made the dropdown
 * look broken through several rounds of fixing everything except this.
 *
 * Rendered in the page's own DOM instead, so the click is an ordinary
 * DOM event. The panel reports its height to Python after every model
 * change, so the window grows to fit the open list.
 */
export default function CogPicker({ row, onPick }) {
  const [open, setOpen] = useState(false)
  const box = useRef(null)

  // Close on any click elsewhere in the page.
  useEffect(() => {
    if (!open) return undefined
    const away = (e) => {
      if (box.current && !box.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', away)
    return () => document.removeEventListener('mousedown', away)
  }, [open])

  const choices = row.choices ?? []
  const current = choices.find((c) => c.current)
  const likely = choices.filter((c) => c.likely)
  const rest = choices.filter((c) => !c.likely)

  const pick = (key) => {
    setOpen(false)
    onPick(key)
  }

  const Item = ({ c }) => (
    <button
      className={`w-full px-2 py-[3px] text-left text-[12px] hover:bg-primary hover:text-primary-content ${
        c.current ? 'font-semibold text-primary' : ''
      }`}
      onClick={() => pick(c.key)}
    >
      {c.display}
    </button>
  )

  return (
    <div ref={box} className="relative w-28 shrink-0">
      <button
        className={`w-full truncate rounded px-1 text-left text-[12px] hover:bg-base-300 ${
          row.identified ? 'opacity-80' : 'italic opacity-60'
        }`}
        onClick={() => setOpen((v) => !v)}
        title={row.identified
          ? `Read as ${row.name} — click to correct it`
          : 'Unidentified — click to say which cog this is'}
      >
        {current ? current.display : `${row.name}?`}
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-[2px] max-h-52 w-40 overflow-y-auto rounded-box border border-base-300 bg-base-200 shadow-xl">
          {likely.length > 0 && (
            <>
              <div className="px-2 pt-1 text-[9px] font-semibold uppercase tracking-wider opacity-40">
                likely
              </div>
              {likely.map((c) => <Item key={c.key} c={c} />)}
              <div className="my-1 border-t border-base-300" />
            </>
          )}
          <div className="px-2 text-[9px] font-semibold uppercase tracking-wider opacity-40">
            all cogs
          </div>
          {rest.map((c) => <Item key={c.key} c={c} />)}
        </div>
      )}
    </div>
  )
}
