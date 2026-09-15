/**
 * API client communicating with visualizer.serve (POST /api/call)
 */

export async function callBridge(fn, payload = null) {
  const res = await fetch('/api/call', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fn, payload }),
  })
  if (!res.ok) {
    throw new Error(`Server returned ${res.status}: ${res.statusText}`)
  }
  const data = await res.json()
  if (data && data.error) {
    throw new Error(data.error)
  }
  return data
}

export async function fetchCatalogue() {
  return callBridge('api_catalogue')
}

export async function fetchRoot(cfg) {
  return callBridge('api_root', cfg)
}

export async function expandDecision(state, depth = 2, objective = null) {
  return callBridge('api_expand_decision', { state, depth, objective })
}

export async function expandAction(state, action, objective = null) {
  return callBridge('api_expand_action', { state, action, objective })
}

export async function fetchCogForecast(state) {
  return callBridge('api_cog_forecast', { state })
}

export async function fetchBestLine(state, depth = 2, objective = null) {
  return callBridge('api_best_line', { state, depth, objective })
}

export async function fetchClimb(state, budget = 24, width = 16) {
  return callBridge('api_climb', { state, budget, width })
}

export async function generateScenario(kind = 'building', seed = null) {
  return callBridge('api_generate_scenario', { kind, seed })
}

export async function randomToon(seed = null) {
  return callBridge('api_random_toon', { seed })
}
