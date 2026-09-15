import React, { useState, useEffect, useCallback, useRef } from 'react'
import {
  fetchCatalogue,
  fetchRoot,
  expandDecision,
  expandAction,
  fetchClimb,
  fetchBestLine,
} from './api'
import DualEngineBanner from './components/DualEngineBanner'
import TreeCanvas, { layoutTree } from './components/TreeCanvas'
import Inspector from './components/Inspector'
import ScenarioBuilder from './components/ScenarioBuilder'

const DEFAULT_CONFIG = {
  toons: [
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
  ],
  cogs: [
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
  ],
}

export default function App() {
  const [catalogue, setCatalogue] = useState(null)
  const [config, setConfig] = useState(DEFAULT_CONFIG)
  const [root, setRoot] = useState(null)
  const [selected, setSelected] = useState(null)
  const [busyNodeId, setBusyNodeId] = useState(null)
  const [busy, setBusy] = useState(false)
  const [showSetup, setShowSetup] = useState(false)
  const [focusId, setFocusId] = useState(null)

  // Dual-Engine settings
  const [engineMode, setEngineMode] = useState('both') // 'ppo' | 'search' | 'both'
  const [preferredEngine, setPreferredEngine] = useState('rl') // 'rl' | 'search'
  const [preset, setPreset] = useState('balanced')
  const [depth, setDepth] = useState(2)
  const [budget, setBudget] = useState(15)

  // Advice & Lines
  const [climbResult, setClimbResult] = useState(null)
  const [bestLine, setBestLine] = useState(null)
  const [treeVersion, setTreeVersion] = useState(0)

  const abortRef = useRef(null)

  // Load catalogue on startup
  useEffect(() => {
    fetchCatalogue()
      .then((cat) => {
        setCatalogue(cat)
        if (cat?.presets?.length) {
          setPreset(cat.presets[0].name)
        }
      })
      .catch((err) => console.error('Failed to load catalogue:', err))
  }, [])

  // Helper to mark paths on nodes
  const updatePathsOnTree = useCallback((rootNode, rlPlan, searchLine) => {
    if (!rootNode) return

    // Clear previous marks
    const clearMarks = (n) => {
      n.onPpoPath = false
      n.onSearchPath = false
      n.onBothPath = false
      n.onPath = false
      if (n.children) n.children.forEach(clearMarks)
    }
    clearMarks(rootNode)

    // Mark root
    rootNode.onPpoPath = true
    rootNode.onSearchPath = true
    rootNode.onBothPath = true
    rootNode.onPath = true

    // RL spine match
    const rlAction = rlPlan?.[0]
    // Search spine match
    const searchAction = searchLine?.[0]?.action

    if (rootNode.children) {
      for (const child of rootNode.children) {
        const cAct = child.action
        if (!cAct) continue

        const isPpoMatch =
          rlAction &&
          cAct.track === rlAction.track &&
          (rlAction.level == null || cAct.level === rlAction.level)

        const isSearchMatch =
          searchAction &&
          cAct.track === searchAction.track &&
          (searchAction.level == null || cAct.level === searchAction.level)

        if (isPpoMatch) child.onPpoPath = true
        if (isSearchMatch) child.onSearchPath = true
        if (isPpoMatch && isSearchMatch) child.onBothPath = true
        if (isPpoMatch || isSearchMatch) child.onPath = true
      }
    }
  }, [])

  // Run solver evaluation (PPO climb + Expectimax search best line)
  const evaluatePosition = useCallback(
    async (rootNode, curConfig) => {
      if (!rootNode?.state) return
      setBusy(true)

      try {
        // Parallel call: PPO climb and Expectimax best line
        const [climbRes, lineRes] = await Promise.all([
          fetchClimb(rootNode.state, budget).catch((err) => ({
            available: false,
            reason: err.message,
          })),
          fetchBestLine(rootNode.state, depth, preset).catch((err) => ({
            line: [],
            error: err.message,
          })),
        ])

        setClimbResult(climbRes)
        const line = lineRes?.line || []
        setBestLine(line)

        // Annotate tree with path ribbons
        updatePathsOnTree(rootNode, climbRes?.plan, line)
        setTreeVersion((v) => v + 1)
      } catch (err) {
        console.error('Error during engine evaluation:', err)
      } finally {
        setBusy(false)
      }
    },
    [budget, depth, preset, updatePathsOnTree],
  )

  // Initialize root when config changes
  const initTree = useCallback(
    async (cfg) => {
      setBusy(true)
      try {
        const r = await fetchRoot(cfg)
        if (r.error) {
          alert(`Error initializing battle tree: ${r.error}`)
          setBusy(false)
          return
        }

        r.open = true
        r.onPpoPath = true
        r.onSearchPath = true
        r.onBothPath = true
        r.onPath = true

        // Initial expansion of root decisions (depth 1)
        const dec = await expandDecision(r.state, 1, preset)
        if (dec?.children) {
          r.children = dec.children.map((c, i) => ({
            ...c,
            id: `${r.id}-a${i}`,
            parent: r,
            open: false,
          }))
        }

        setRoot(r)
        setSelected(r)
        setFocusId(r.id)

        // Run full dual-engine evaluation
        evaluatePosition(r, cfg)
      } catch (err) {
        console.error('Failed to init tree:', err)
        alert(`Failed to build tree: ${err.message}`)
        setBusy(false)
      }
    },
    [evaluatePosition, preset],
  )

  // Boot on startup
  useEffect(() => {
    initTree(config)
  }, [])

  // Expand node children dynamically
  const handleExpandNode = async (node) => {
    if (!node || busyNodeId) return
    setBusyNodeId(node.id)

    try {
      if (node.kind === 'decision') {
        const res = await expandDecision(node.state, 1, preset)
        if (res?.children) {
          node.children = res.children.map((c, i) => ({
            ...c,
            id: `${node.id}-a${i}`,
            parent: node,
            open: false,
          }))
          node.open = true
          node.pathOnly = false
        }
      } else if (node.kind === 'action') {
        const res = await expandAction(node.parent?.state || node.state, node.action, preset)
        if (res?.children) {
          node.children = res.children.map((c, i) => ({
            ...c,
            id: `${node.id}-o${i}`,
            parent: node,
            open: false,
          }))
          node.open = true
          node.pathOnly = false
        }
      }
      setTreeVersion((v) => v + 1)
    } catch (err) {
      console.error('Failed to expand node:', err)
    } finally {
      setBusyNodeId(null)
    }
  }

  // Toggle node open / select
  const handleToggleNode = async (node) => {
    if (node.kind === 'more') {
      if (node.owner) {
        node.owner.pathOnly = false
        setTreeVersion((v) => v + 1)
      }
      return
    }

    setSelected(node)

    // If node has children, toggle them
    if (node.children && node.children.length > 0) {
      node.open = !node.open
      setTreeVersion((v) => v + 1)
    } else if (node.kind !== 'terminal') {
      // Lazy expand on click
      await handleExpandNode(node)
    }
  }

  // Collapse all except root
  const handleCollapseAll = () => {
    if (!root) return
    const walk = (n) => {
      if (n !== root) n.open = false
      if (n.children) n.children.forEach(walk)
    }
    walk(root)
    root.open = true
    setTreeVersion((v) => v + 1)
  }

  // Show best path along active engine
  const handleShowBestPath = () => {
    if (!root) return
    const activeEnginePath =
      engineMode === 'ppo' || (engineMode === 'both' && preferredEngine === 'rl')
        ? 'onPpoPath'
        : 'onSearchPath'

    let deepest = root
    const walk = (n) => {
      if (n[activeEnginePath] || n.onBothPath) {
        n.open = true
        n.pathOnly = true
        deepest = n
        if (n.children) n.children.forEach(walk)
      }
    }
    walk(root)
    setFocusId(deepest.id)
    setSelected(deepest)
    setTreeVersion((v) => v + 1)
  }

  // Apply new scenario config from ScenarioBuilder
  const handleApplyConfig = (newConfig) => {
    setConfig(newConfig)
    setShowSetup(false)
    initTree(newConfig)
  }

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden bg-[#F4F1EA] text-amber-950 font-sans select-none">
      {/* TOP: DUAL-ENGINE CONTROL & ADVICE BANNER */}
      <DualEngineBanner
        engineMode={engineMode}
        setEngineMode={setEngineMode}
        preset={preset}
        setPreset={(p) => {
          setPreset(p)
          if (root) evaluatePosition(root, config)
        }}
        presets={catalogue?.presets || []}
        depth={depth}
        setDepth={(d) => {
          setDepth(d)
          if (root) evaluatePosition(root, config)
        }}
        budget={budget}
        setBudget={(b) => {
          setBudget(b)
          if (root) evaluatePosition(root, config)
        }}
        climbResult={climbResult}
        bestLine={bestLine}
        preferredEngine={preferredEngine}
        setPreferredEngine={setPreferredEngine}
        onShowBestPath={handleShowBestPath}
        onCollapseAll={handleCollapseAll}
        onFitView={() => setFocusId(root?.id)}
        onToggleSetup={() => setShowSetup((v) => !v)}
        showSetup={showSetup}
        busy={busy}
      />

      {/* MAIN WORKSPACE: TREE CANVAS (FLEX-1) + INSPECTOR SIDEBAR */}
      <div className="flex flex-1 min-h-0 relative">
        {root ? (
          <TreeCanvas
            key={treeVersion}
            root={root}
            selected={selected}
            setSelected={setSelected}
            engineMode={engineMode}
            busyNodeId={busyNodeId}
            onToggleNode={handleToggleNode}
            focusId={focusId}
          />
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center gap-3 text-amber-900/60">
            <span className="loading loading-spinner loading-lg text-sky-600" />
            <span className="font-black text-sm">Building Battle Tree…</span>
          </div>
        )}

        {/* RIGHT INSPECTOR PANEL */}
        <Inspector
          node={selected || root}
          engineMode={engineMode}
          bestLine={bestLine}
          climbResult={climbResult}
          onExpand={handleExpandNode}
          onCollapse={(n) => {
            n.open = false
            setTreeVersion((v) => v + 1)
          }}
          busy={busy || Boolean(busyNodeId)}
        />
      </div>

      {/* SCENARIO BUILDER MODAL */}
      {showSetup && (
        <ScenarioBuilder
          catalogue={catalogue}
          initialConfig={config}
          onApply={handleApplyConfig}
          onClose={() => setShowSetup(false)}
          busy={busy}
        />
      )}
    </div>
  )
}
