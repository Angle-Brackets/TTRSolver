import React, { useRef, useEffect, useCallback } from 'react'
import { GagIcon, CogAvatar } from './Icons'

const NODE_W = 110
const CARD_H = 62
const COL_W = 124
const ROW_H = 106
const PAD_X = 30
const PAD_Y = 24

const pct = (p) => `${(p * 100).toFixed(p < 0.1 ? 1 : 0)}%`

export function shown(node) {
  if (!node.open || !node.children || !node.children.length) return []
  if (!node.pathOnly) return node.children
  const on = node.children.filter((c) => c.onPpoPath || c.onSearchPath || c.onPath)
  if (!on.length) return node.children
  const hidden = node.children.length - on.length
  if (!hidden) return on
  if (!node._more) {
    node._more = {
      kind: 'more',
      id: `more-${node.id}`,
      parent: node,
      label: `+${hidden} more`,
      owner: node,
    }
  }
  node._more.label = `+${hidden} more`
  return [...on, node._more]
}

export function layoutTree(root) {
  let col = 0
  let maxDepth = 0
  let maxX = 0

  const walk = (node, depth) => {
    node.y = PAD_Y + depth * ROW_H
    node.depth = depth
    maxDepth = Math.max(maxDepth, depth)
    const kids = shown(node)
    if (kids.length) {
      kids.forEach((c) => walk(c, depth + 1))
      node.x = (kids[0].x + kids[kids.length - 1].x) / 2
    } else {
      node.x = PAD_X + col * COL_W
      col += 1
    }
    maxX = Math.max(maxX, node.x)
  }

  walk(root, 0)
  return { maxDepth, maxX }
}

export function visibleEdges(root) {
  const out = []
  const walk = (n) => {
    for (const c of shown(n)) {
      out.push([n, c])
      walk(c)
    }
  }
  walk(root)
  return out
}

function NodeCard({
  node,
  selected,
  engineMode,
  onSelect,
  busy,
  draggedRef,
}) {
  const isAction = node.kind === 'action'
  const isTerminal = node.kind === 'terminal'
  const isMore = node.kind === 'more'
  const isDecision = node.kind === 'decision'
  const isWin = isTerminal && !/lost|sad/i.test(node.label || '')
  const isLoss = isTerminal && /lost|sad/i.test(node.label || '')

  const track = node.action?.track || 'none'
  const level = node.action?.level

  // Engine path status
  const onPpo = Boolean(node.onPpoPath)
  const onSearch = Boolean(node.onSearchPath)
  const onBoth = onPpo && onSearch

  let pathClass = ''
  if (engineMode === 'both') {
    if (onBoth) pathClass = 'on-both-path ring-2 ring-amber-400'
    else if (onPpo) pathClass = 'on-ppo-path ring-2 ring-emerald-500'
    else if (onSearch) pathClass = 'on-search-path ring-2 ring-sky-500'
  } else if (engineMode === 'ppo' && onPpo) {
    pathClass = 'on-ppo-path ring-2 ring-emerald-500'
  } else if (engineMode === 'search' && onSearch) {
    pathClass = 'on-search-path ring-2 ring-sky-500'
  }

  const headline =
    node.ev != null
      ? `${node.ev > 0 ? '+' : ''}${node.ev.toFixed(0)}`
      : node.prob != null
      ? pct(node.prob)
      : null

  return (
    <div
      className={`tree-node-card track-${track} ${selected ? 'selected' : ''} ${pathClass}`}
      style={{ left: node.x, top: node.y }}
      onClick={(e) => {
        e.stopPropagation()
        if (draggedRef.current) return
        onSelect(node)
      }}
      title={node.label}
    >
      {/* Non-emoji Engine Tag Chip in Both Mode */}
      {engineMode === 'both' && (onPpo || onSearch) && (
        <div className="absolute -top-2.5 right-1 flex items-center gap-0.5">
          {onBoth ? (
            <span className="badge badge-xs bg-amber-500 text-white border-amber-600 font-black text-[7.5px] px-1 shadow-xs">
              BOTH
            </span>
          ) : onPpo ? (
            <span className="badge badge-xs bg-emerald-600 text-white border-emerald-700 font-black text-[7.5px] px-1 shadow-xs">
              RL
            </span>
          ) : (
            <span className="badge badge-xs bg-sky-600 text-white border-sky-700 font-black text-[7.5px] px-1 shadow-xs">
              SEARCH
            </span>
          )}
        </div>
      )}

      {/* TOP ROW: Icon or Cog strip */}
      <div className="flex items-center justify-center gap-1 w-full min-w-0">
        {isAction && track && level ? (
          <GagIcon track={track} level={level} size="size-6" />
        ) : isDecision && node.cog_icons && node.cog_icons.length ? (
          <div className="flex items-center gap-0.5 max-w-full overflow-hidden">
            {node.cog_icons.slice(0, 4).map((ic, i) => (
              <img
                key={i}
                src={`assets/${ic}`}
                alt=""
                className="size-4 object-contain"
                onError={(e) => { e.target.style.display = 'none' }}
              />
            ))}
          </div>
        ) : isWin ? (
          <span className="text-emerald-700 font-black text-[11px]">🏆 VICTORY</span>
        ) : isLoss ? (
          <span className="text-rose-700 font-black text-[11px]">💀 SAD</span>
        ) : isMore ? (
          <span className="text-amber-800 font-black text-[11px]">{node.label}</span>
        ) : (
          <span className="text-amber-900/60 font-black text-[10px]">Toon Turn</span>
        )}

        {busy && <span className="loading loading-spinner loading-xs text-sky-600" />}
      </div>

      {/* BOTTOM ROW: EV or Prob & Details */}
      {!isMore && (
        <div className="flex items-center justify-between w-full px-1 text-[9.5px] font-black leading-tight text-amber-950">
          <span className="truncate max-w-[65px]" title={node.label}>
            {isAction ? (node.action?.track?.toUpperCase() || '') : (node.label || '')}
          </span>

          {headline && (
            <span
              className={`rounded px-1 py-0.2 font-mono text-[9px] shadow-2xs ${
                node.ev != null
                  ? 'bg-amber-100 text-amber-950 border border-amber-900/15'
                  : 'bg-white text-emerald-800 border border-emerald-300'
              }`}
            >
              {headline}
            </span>
          )}
        </div>
      )}
    </div>
  )
}

export default function TreeCanvas({
  root,
  selected,
  setSelected,
  engineMode,
  busyNodeId,
  onToggleNode,
  focusId,
}) {
  const canvasRef = useRef(null)
  const dragRef = useRef(null)
  const movedRef = useRef(false)
  const [view, setView] = React.useState({ x: 40, y: 30, z: 1.0 })

  const { maxDepth, maxX } = layoutTree(root)
  const edges = visibleEdges(root)
  const width = Math.max(800, maxX + NODE_W + 100)
  const height = Math.max(600, PAD_Y + (maxDepth + 1) * ROW_H + 100)

  // Fit to screen helper
  const fitToScreen = useCallback(() => {
    if (!canvasRef.current) return
    const box = canvasRef.current.getBoundingClientRect()
    let minX = Infinity, maxRight = -Infinity, maxBottom = -Infinity
    const walk = (n) => {
      minX = Math.min(minX, n.x)
      maxRight = Math.max(maxRight, n.x + NODE_W)
      maxBottom = Math.max(maxBottom, n.y + CARD_H)
      shown(n).forEach(walk)
    }
    walk(root)
    const w = Math.max(1, maxRight - minX)
    const h = Math.max(1, maxBottom)
    const z = Math.min(2.0, Math.max(0.2, Math.min((box.width - 60) / w, (box.height - 60) / h)))
    setView({ z, x: (box.width - w * z) / 2 - minX * z, y: 30 })
  }, [root])

  // Center on focused node
  useEffect(() => {
    if (!focusId || !canvasRef.current) return
    let target = null
    const find = (n) => {
      if (n.id === focusId) { target = n; return }
      shown(n).forEach(find)
    }
    find(root)
    if (!target) return

    const box = canvasRef.current.getBoundingClientRect()
    setView((v) => {
      const sx = target.x * v.z + v.x
      const sy = target.y * v.z + v.y
      const pad = 60
      const inside = sx > pad && sx < box.width - pad - NODE_W * v.z && sy > pad && sy < box.height - pad
      if (inside) return v
      return {
        ...v,
        x: box.width / 2 - (target.x + NODE_W / 2) * v.z,
        y: Math.max(pad, box.height / 3 - target.y * v.z),
      }
    })
  }, [focusId, root])

  return (
    <div
      id="canvas"
      ref={canvasRef}
      className={`relative flex-1 overflow-hidden select-none cursor-grab active:cursor-grabbing bg-[#F4F1EA] ${
        dragRef.current ? 'cursor-grabbing' : ''
      }`}
      onWheel={(e) => {
        e.preventDefault()
        const box = e.currentTarget.getBoundingClientRect()
        const cx = e.clientX - box.left
        const cy = e.clientY - box.top
        setView((v) => {
          const z = Math.min(2.2, Math.max(0.2, v.z * (e.deltaY < 0 ? 1.12 : 1 / 1.12)))
          return {
            z,
            x: cx - (cx - v.x) * (z / v.z),
            y: cy - (cy - v.y) * (z / v.z),
          }
        })
      }}
      onPointerDown={(e) => {
        if (e.button !== 0) return
        dragRef.current = { x: e.clientX, y: e.clientY, ox: view.x, oy: view.y, captured: false }
        movedRef.current = false
      }}
      onPointerMove={(e) => {
        const d = dragRef.current
        if (!d) return
        const dx = e.clientX - d.x
        const dy = e.clientY - d.y
        if (!movedRef.current && Math.abs(dx) + Math.abs(dy) <= 4) return
        movedRef.current = true
        if (!d.captured) {
          d.captured = true
          e.currentTarget.setPointerCapture(e.pointerId)
        }
        setView((v) => ({ ...v, x: d.ox + dx, y: d.oy + dy }))
      }}
      onPointerUp={(e) => {
        const d = dragRef.current
        dragRef.current = null
        if (d && d.captured) e.currentTarget.releasePointerCapture(e.pointerId)
        if (!movedRef.current && e.target === e.currentTarget) {
          setSelected(root)
        }
      }}
    >
      <div
        className="absolute left-0 top-0 will-change-transform"
        style={{
          width,
          height,
          transform: `translate(${view.x}px, ${view.y}px) scale(${view.z})`,
          transformOrigin: '0 0',
        }}
      >
        {/* SVG BEZIER CONNECTOR EDGES */}
        <svg
          width={width}
          height={height}
          style={{ position: 'absolute', left: 0, top: 0, pointerEvents: 'none' }}
        >
          {edges.map(([a, b], i) => {
            const x1 = a.x + NODE_W / 2
            const y1 = a.y + CARD_H
            const x2 = b.x + NODE_W / 2
            const y2 = b.y
            const mid = (y1 + y2) / 2

            // Determine edge line colors
            const ppoEdge = (a.onPpoPath && b.onPpoPath) || (a.onPath && b.onPath)
            const searchEdge = (a.onSearchPath && b.onSearchPath) || (a.onPath && b.onPath)
            const bothEdge = ppoEdge && searchEdge

            let strokeColor = '#CBD5E1'
            let strokeWidth = 1.6

            if (engineMode === 'both') {
              if (bothEdge) {
                strokeColor = '#F59E0B'
                strokeWidth = 3.2
              } else if (ppoEdge) {
                strokeColor = '#10B981'
                strokeWidth = 2.8
              } else if (searchEdge) {
                strokeColor = '#0EA5E9'
                strokeWidth = 2.8
              }
            } else if (engineMode === 'ppo' && ppoEdge) {
              strokeColor = '#10B981'
              strokeWidth = 3.0
            } else if (engineMode === 'search' && searchEdge) {
              strokeColor = '#0EA5E9'
              strokeWidth = 3.0
            }

            return (
              <path
                key={i}
                d={`M${x1},${y1} C${x1},${mid} ${x2},${mid} ${x2},${y2}`}
                fill="none"
                stroke={strokeColor}
                strokeWidth={strokeWidth}
                strokeLinecap="round"
              />
            )
          })}
        </svg>

        {/* NODES LAYER */}
        {(() => {
          const out = []
          const walk = (n) => {
            out.push(
              <NodeCard
                key={n.id}
                node={n}
                selected={selected && selected.id === n.id}
                engineMode={engineMode}
                busy={busyNodeId === n.id}
                draggedRef={movedRef}
                onSelect={onToggleNode}
              />,
            )
            shown(n).forEach(walk)
          }
          walk(root)
          return out
        })()}
      </div>
    </div>
  )
}
