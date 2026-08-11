import React, { useState } from "react";
import {
  ChevronRight, ChevronDown, Play, Percent, Settings,
  Trophy, Skull, RefreshCw, Info, MoreHorizontal,
} from "lucide-react";

/* ------------------------------------------------------------------ */
/* Data — a hardcoded subset of solver/data/; see ../docs/          */
/* data-confidence.md for confirmed vs. demo/placeholder numbers and   */
/* ./README.md for why this copy exists at all.                        */
/* Trap per-level damage and Flunky attack accuracy are not            */
/* yet confirmed from source (Appendix C gap); they're marked isDemo   */
/* and shown with a dashed badge in the UI rather than silently mixed  */
/* in with the confirmed numbers.                                     */
/* ------------------------------------------------------------------ */

const TOON_GAGS = [
  { id: "throw1", track: "throw", level: 1, name: "Cupcake", propAcc: 75, dmgMax: 6, confirmed: true },
  { id: "throw3", track: "throw", level: 3, name: "Cream Pie Slice", propAcc: 75, dmgMax: 17, confirmed: true },
  { id: "trap1", track: "trap", level: 1, name: "Banana Peel", propAcc: 100, dmg: 10, confirmed: false },
  { id: "lure2", track: "lure", level: 2, name: "Hypno Goggles", propAcc: 50, confirmed: true },
];

const TRACK_EXP_BONUS = 60; // (7-1)*10, assumes a fully-trained track — [CONFIRMED] formula
const ACCURACY_CAP = 95;
const TGT_DEF = { 1: -2, 2: -5, 3: -10, 4: -12, 5: -15, 6: -25, 7: -30, 8: -35, 9: -40, 10: -45, 11: -50, 12: -55 };

const FLUNKY = {
  levels: [1, 2, 3, 4, 5],
  attacks: {
    pound_key: { name: "Pound Key", freq: [30, 35, 40, 45, 50], dmg: [2, 2, 3, 4, 6] },
    shred: { name: "Shred", freq: [10, 15, 20, 25, 30], dmg: [3, 4, 5, 6, 7] },
    clip_on_tie: { name: "Clip-on Tie", freq: [60, 50, 40, 30, 20], dmg: [1, 1, 2, 2, 3] },
  },
  accuracyDemo: 75, // placeholder — real Bossbot accuracy (Appendix C) not yet transcribed
};

const cogMaxHp = (level) => { const x = level + 1; return x * (x + 1); };

const ACTION_DISPLAY_CAP = 4;
const OUTCOME_DISPLAY_CAP = 5;

/* ------------------------------------------------------------------ */
/* Pure game logic                                                     */
/* ------------------------------------------------------------------ */

const cloneState = (s) => JSON.parse(JSON.stringify(s));

function calcToonAccuracy(gag, cogLevel) {
  if (gag.track === "trap") return 100;
  const acc = gag.propAcc + TRACK_EXP_BONUS + TGT_DEF[cogLevel] + 0; // bonus=0: solo toon, see notes
  return Math.min(acc, ACCURACY_CAP);
}

function legalActions(state) {
  const actions = [];
  for (const gag of TOON_GAGS) {
    if ((state.gagCounts[gag.id] || 0) <= 0) continue;
    state.cogs.forEach((cog, i) => {
      if (cog.dead) return;
      if (gag.track === "trap" && (cog.trapped || cog.lured)) return;
      actions.push({ gag, targetIndex: i });
    });
  }
  return actions;
}

function applyToonAction(state, action, hit) {
  const s = cloneState(state);
  s.gagCounts[action.gag.id] = (s.gagCounts[action.gag.id] || 0) - 1;
  if (!hit) return { state: s, note: "missed" };
  const cog = s.cogs[action.targetIndex];
  if (action.gag.track === "trap") {
    cog.trapped = true;
    cog.trapGagId = action.gag.id;
    return { state: s, note: "trap laid" };
  }
  if (action.gag.track === "lure") {
    if (cog.trapped) {
      const trapGag = TOON_GAGS.find((g) => g.id === cog.trapGagId);
      const dmg = trapGag.dmg;
      cog.hp -= dmg;
      cog.trapped = false;
      cog.trapGagId = null;
      if (cog.hp <= 0) cog.dead = true;
      return { state: s, note: `trap triggered, ${dmg} dmg` };
    }
    cog.lured = true;
    return { state: s, note: "lured" };
  }
  const dmg = action.gag.dmgMax;
  cog.hp -= dmg;
  if (cog.hp <= 0) cog.dead = true;
  return { state: s, note: `${dmg} dmg` };
}

const isWin = (state) => state.cogs.every((c) => c.dead);

function cogDamageDistribution(cog) {
  if (cog.dead || cog.lured) return [{ dmg: 0, prob: 1 }];
  const relIdx = cog.level - FLUNKY.levels[0];
  const dist = {};
  let missAccum = 0;
  for (const key in FLUNKY.attacks) {
    const atk = FLUNKY.attacks[key];
    const pAttack = atk.freq[relIdx] / 100;
    const pHit = FLUNKY.accuracyDemo / 100;
    const dmg = atk.dmg[relIdx];
    dist[dmg] = (dist[dmg] || 0) + pAttack * pHit;
    missAccum += pAttack * (1 - pHit);
  }
  dist[0] = (dist[0] || 0) + missAccum;
  return Object.entries(dist).map(([d, p]) => ({ dmg: Number(d), prob: p }));
}

function convolve(dists) {
  let result = [{ dmg: 0, prob: 1 }];
  for (const dist of dists) {
    const next = [];
    for (const r of result) for (const d of dist) next.push({ dmg: r.dmg + d.dmg, prob: r.prob * d.prob });
    const merged = {};
    next.forEach((o) => { merged[o.dmg] = (merged[o.dmg] || 0) + o.prob; });
    result = Object.entries(merged).map(([d, p]) => ({ dmg: Number(d), prob: p }));
  }
  return result.sort((a, b) => b.prob - a.prob);
}

function buildOutcomeNode(state, dmg, prob, depthRemaining, edgeLabel) {
  const s = cloneState(state);
  s.toonLaff = Math.max(0, s.toonLaff - dmg);
  let node;
  if (s.toonLaff <= 0) node = { type: "terminal-loss", state: s, label: "Toon is sad — battle lost" };
  else if (isWin(s)) node = { type: "terminal-win", state: s, label: "All cogs defeated" };
  else if (depthRemaining - 1 <= 0) node = { type: "cutoff", state: s, label: "Depth limit reached" };
  else node = { type: "decision", state: s, depthRemaining: depthRemaining - 1, label: "Toon's turn", children: null };
  node.probability = prob;
  node.edgeLabel = edgeLabel;
  return node;
}

function buildCogPhaseOutcomes(state, depthRemaining) {
  const alive = state.cogs.filter((c) => !c.dead);
  const dists = alive.map(cogDamageDistribution);
  const joint = dists.length ? convolve(dists) : [{ dmg: 0, prob: 1 }];
  const capped = joint.slice(0, OUTCOME_DISPLAY_CAP);
  const rest = joint.slice(OUTCOME_DISPLAY_CAP);
  const nodes = capped.map((o) => buildOutcomeNode(state, o.dmg, o.prob, depthRemaining, `${o.dmg} dmg to Toon`));
  if (rest.length) {
    const restProb = rest.reduce((s, o) => s + o.prob, 0);
    const avgDmg = Math.round(rest.reduce((s, o) => s + o.dmg * o.prob, 0) / restProb);
    nodes.push(buildOutcomeNode(state, avgDmg, restProb, depthRemaining, `~${avgDmg} dmg (${rest.length} rarer outcomes, bucketed)`));
  }
  return nodes;
}

function buildPostToonNode(state, prob, edgeLabel, depthRemaining) {
  if (isWin(state)) return { type: "terminal-win", state, probability: prob, edgeLabel, label: "All cogs defeated" };
  return {
    type: "chance-cog", state, probability: prob, edgeLabel,
    label: "Cogs counter-attack", children: buildCogPhaseOutcomes(state, depthRemaining),
  };
}

function buildChanceHitNode(state, action, depthRemaining) {
  const cogLevel = state.cogs[action.targetIndex].level;
  const acc = calcToonAccuracy(action.gag, cogLevel);
  const pHit = acc / 100;
  const { state: hitState, note } = applyToonAction(state, action, true);
  const children = [buildPostToonNode(hitState, pHit, `Hit (${acc}%) — ${note}`, depthRemaining)];
  if (pHit < 1) {
    const { state: missState } = applyToonAction(state, action, false);
    children.push(buildPostToonNode(missState, 1 - pHit, `Miss (${100 - acc}%)`, depthRemaining));
  }
  const cog = state.cogs[action.targetIndex];
  return {
    type: "chance-hit",
    label: `${action.gag.name} (Lv${action.gag.level}) → Cog ${action.targetIndex + 1} (Lv${cog.level})`,
    isDemoData: !action.gag.confirmed,
    children,
  };
}

const expandDecision = (node) => legalActions(node.state).map((a) => buildChanceHitNode(node.state, a, node.depthRemaining));

/* ------------------------------------------------------------------ */
/* UI                                                                   */
/* ------------------------------------------------------------------ */

const TYPE_STYLE = {
  decision: { color: "#F2A93B", icon: Play, badge: "Your move" },
  "chance-hit": { color: "#6FA3C7", icon: Percent, badge: "Chance" },
  "chance-cog": { color: "#8A93A8", icon: Settings, badge: "Chance" },
  "terminal-win": { color: "#4CAF7D", icon: Trophy, badge: "Win" },
  "terminal-loss": { color: "#D9564A", icon: Skull, badge: "Loss" },
  cutoff: { color: "#5B6270", icon: MoreHorizontal, badge: "Cutoff" },
};

function CogRow({ cog, idx }) {
  if (cog.dead) return <span className="opacity-40 line-through mr-3">Cog {idx + 1}</span>;
  return (
    <span className="mr-3 inline-flex items-center gap-1">
      <span>Cog {idx + 1} L{cog.level}</span>
      <span style={{ fontFamily: "'JetBrains Mono', monospace" }} className="text-xs opacity-80">
        {cog.hp}/{cog.maxHp}
      </span>
      {cog.trapped && <span title="Trapped">🪤</span>}
      {cog.lured && <span title="Lured">💫</span>}
    </span>
  );
}

function TreeNode({ node, depth }) {
  const [expanded, setExpanded] = useState(depth === 0);
  const [children, setChildren] = useState(node.children || null);
  const [showAll, setShowAll] = useState(false);

  const isLeaf = ["terminal-win", "terminal-loss", "cutoff"].includes(node.type);
  const style = TYPE_STYLE[node.type];
  const Icon = style.icon;

  React.useEffect(() => {
    if (expanded && children === null && !isLeaf) {
      setChildren(node.type === "decision" ? expandDecision(node) : node.children);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [expanded]);

  const toggle = () => {
    if (!isLeaf) setExpanded((e) => !e);
  };

  const shown = children && !showAll && children.length > ACTION_DISPLAY_CAP
    ? children.slice(0, ACTION_DISPLAY_CAP) : children;
  const hiddenCount = children ? children.length - (shown ? shown.length : 0) : 0;

  return (
    <div style={{ marginLeft: depth === 0 ? 0 : 14 }}>
      <div
        className="rounded-lg border px-3 py-2 mb-1.5 cursor-pointer select-none"
        style={{ borderColor: style.color + "55", background: "#1B1E24" }}
        onClick={toggle}
      >
        <div className="flex items-center gap-2">
          {!isLeaf && (expanded ? <ChevronDown size={14} className="opacity-60 shrink-0" /> : <ChevronRight size={14} className="opacity-60 shrink-0" />)}
          <Icon size={15} style={{ color: style.color }} className="shrink-0" />
          <span
            className="text-xs uppercase tracking-wide font-semibold px-1.5 py-0.5 rounded"
            style={{ color: style.color, background: style.color + "22" }}
          >
            {style.badge}
          </span>
          {node.probability != null && (
            <span style={{ fontFamily: "'JetBrains Mono', monospace" }} className="text-xs opacity-70">
              p={node.probability.toFixed(2)}
            </span>
          )}
          {node.isDemoData && (
            <span className="text-xs px-1 py-0.5 rounded border border-dashed opacity-70" style={{ borderColor: "#D9564A" }}>
              demo data
            </span>
          )}
        </div>
        {node.edgeLabel && <div className="text-xs opacity-70 mt-0.5 ml-6">{node.edgeLabel}</div>}
        <div className="text-sm mt-0.5 ml-6" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
          {node.label}
        </div>
        <div className="text-xs mt-1 ml-6 opacity-80">
          <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>Laff {node.state.toonLaff}</span>
          <span className="mx-2 opacity-40">|</span>
          {node.state.cogs.map((c, i) => <CogRow key={i} cog={c} idx={i} />)}
        </div>
      </div>

      {expanded && children && (
        <div className="border-l pl-2" style={{ borderColor: "#33373f" }}>
          {children.length === 0 && (
            <div className="text-xs opacity-50 italic ml-4 mb-2">No legal actions left — Toon is out of usable gags.</div>
          )}
          {shown.map((c, i) => <TreeNode key={i} node={c} depth={depth + 1} />)}
          {hiddenCount > 0 && (
            <button
              className="text-xs ml-4 mb-2 px-2 py-1 rounded border opacity-80 hover:opacity-100"
              style={{ borderColor: "#5B6270" }}
              onClick={(e) => { e.stopPropagation(); setShowAll(true); }}
            >
              + {hiddenCount} more {node.type === "decision" ? "actions" : "outcomes"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */

export default function ToontownTreeExplorer() {
  const [numCogs, setNumCogs] = useState(2);
  const [cogLevels, setCogLevels] = useState([2, 3]);
  const [toonLaff, setToonLaff] = useState(50);
  const [depth, setDepth] = useState(2);
  const [treeKey, setTreeKey] = useState(0);

  const buildRoot = () => {
    const cogs = Array.from({ length: numCogs }, (_, i) => {
      const lvl = cogLevels[i] || 2;
      return { level: lvl, hp: cogMaxHp(lvl), maxHp: cogMaxHp(lvl), dead: false, trapped: false, lured: false, trapGagId: null };
    });
    return {
      type: "decision", depthRemaining: depth, probability: 1, label: "Toon's turn", children: null,
      state: { toonLaff, cogs, gagCounts: { throw1: 5, throw3: 3, trap1: 2, lure2: 3 } },
    };
  };

  const [root, setRoot] = useState(buildRoot());

  const rebuild = () => { setRoot(buildRoot()); setTreeKey((k) => k + 1); };

  return (
    <div className="min-h-screen p-4" style={{ background: "#14161A", color: "#EDEFF2" }}>
      <style>{`@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=JetBrains+Mono:wght@400;600&display=swap');`}</style>

      <h1 className="text-xl font-bold mb-1" style={{ fontFamily: "'Space Grotesk', sans-serif" }}>
        Cog Battle Tree Explorer
      </h1>
      <p className="text-xs opacity-60 mb-4">
        Lazy expectimax tree — nodes compute their children only when you tap them, so it never eagerly blows up.
        Action lists and outcome branches beyond the cap collapse into a "+N more" button.
      </p>

      <div className="rounded-lg border p-3 mb-4 text-xs" style={{ borderColor: "#33373f", background: "#1B1E24" }}>
        <div className="flex items-center gap-1.5 mb-2 font-semibold opacity-80">
          <Info size={13} /> Data confidence
        </div>
        <div className="opacity-70 leading-relaxed">
          Accuracy formula, tgtDef, Throw/Lure propAcc, and Flunky attack frequency/damage are confirmed from
          source. Trap-per-level damage and Flunky cog accuracy are placeholder <span className="border border-dashed px-1 rounded" style={{ borderColor: "#D9564A" }}>demo data</span> — the real numbers aren't transcribed yet.
        </div>
      </div>

      <div className="rounded-lg border p-3 mb-4 grid grid-cols-2 gap-3 text-xs" style={{ borderColor: "#33373f", background: "#1B1E24" }}>
        <label className="flex flex-col gap-1">
          <span className="opacity-70"># Cogs</span>
          <select
            className="bg-transparent border rounded px-2 py-1"
            style={{ borderColor: "#5B6270" }}
            value={numCogs}
            onChange={(e) => setNumCogs(Number(e.target.value))}
          >
            <option value={1}>1</option>
            <option value={2}>2</option>
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="opacity-70">Toon Laff</span>
          <input
            type="range" min={10} max={80} value={toonLaff}
            onChange={(e) => setToonLaff(Number(e.target.value))}
          />
          <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>{toonLaff}</span>
        </label>
        {Array.from({ length: numCogs }).map((_, i) => (
          <label className="flex flex-col gap-1" key={i}>
            <span className="opacity-70">Cog {i + 1} level</span>
            <select
              className="bg-transparent border rounded px-2 py-1"
              style={{ borderColor: "#5B6270" }}
              value={cogLevels[i] || 2}
              onChange={(e) => {
                const next = [...cogLevels]; next[i] = Number(e.target.value); setCogLevels(next);
              }}
            >
              {[1, 2, 3, 4, 5].map((l) => <option key={l} value={l}>{l}</option>)}
            </select>
          </label>
        ))}
        <label className="flex flex-col gap-1">
          <span className="opacity-70">Depth N</span>
          <input type="range" min={1} max={4} value={depth} onChange={(e) => setDepth(Number(e.target.value))} />
          <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>{depth} rounds</span>
        </label>
        <button
          onClick={rebuild}
          className="col-span-2 mt-1 flex items-center justify-center gap-1.5 rounded py-1.5 font-semibold"
          style={{ background: "#F2A93B", color: "#14161A" }}
        >
          <RefreshCw size={13} /> Rebuild tree
        </button>
      </div>

      <div className="rounded-lg border p-3 mb-4 flex flex-wrap gap-3 text-xs" style={{ borderColor: "#33373f", background: "#1B1E24" }}>
        {Object.entries(TYPE_STYLE).map(([k, v]) => {
          const Icon = v.icon;
          return (
            <span key={k} className="flex items-center gap-1">
              <Icon size={12} style={{ color: v.color }} /> {v.badge}
            </span>
          );
        })}
      </div>

      <div key={treeKey}>
        <TreeNode node={root} depth={0} />
      </div>
    </div>
  );
}
