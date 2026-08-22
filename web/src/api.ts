import type { AskResponse, Meta, Neighbour, Player, Profile, SimilarOpts } from './types'

const base = '/api'

async function get<T>(path: string): Promise<T> {
  const r = await fetch(base + path)
  if (!r.ok) {
    let detalle = r.statusText
    try {
      detalle = (await r.json()).detail ?? detalle
    } catch {
      // el cuerpo no era JSON; nos quedamos con el statusText
    }
    throw new Error(`${r.status} ${detalle}`)
  }
  return r.json() as Promise<T>
}

export const getMeta = () => get<Meta>('/meta')

export const searchPlayers = (
  q: string,
  { league, role, limit = 30 }: { league?: string; role?: string; limit?: number } = {},
) => {
  const p = new URLSearchParams({ limit: String(limit) })
  if (q) p.set('q', q)
  if (league) p.set('league', league)
  if (role) p.set('role', role)
  return get<Player[]>(`/players?${p}`)
}

export const getPlayer = (id: number) => get<Profile>(`/players/${id}`)

export const getSimilar = (id: number, { k = 8, role, sameRole, league }: SimilarOpts = {}) => {
  const p = new URLSearchParams({ k: String(k) })
  if (role) p.set('role', role)
  if (sameRole) p.set('same_role', 'true')
  if (league) p.set('league', league)
  return get<Neighbour[]>(`/similar/${id}?${p}`)
}

export const compare = (ids: number[]) => get<Profile[]>(`/compare?ids=${ids.join(',')}`)

export async function ask(q: string): Promise<AskResponse> {
  const r = await fetch(`${base}/ask`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ q }),
  })
  if (!r.ok) {
    let detalle = r.statusText
    try {
      detalle = (await r.json()).detail ?? detalle
    } catch {
      // cuerpo no JSON
    }
    throw new Error(`${r.status} ${detalle}`)
  }
  return r.json() as Promise<AskResponse>
}

// cortas a proposito: 17 ejes en un circulo no admiten nombres largos sin
// solaparse, y radar-check.mjs lo verifica
export const LABEL: Record<string, string> = {
  pass_p90: 'Passes', shot_p90: 'Shots', dribble_p90: 'Dribbles',
  pressure_p90: 'Pressure', carry_p90: 'Carries', ball_receipt_p90: 'Receipts',
  duel_p90: 'Duels', interception_p90: 'Interc.', clearance_p90: 'Clear.',
  prog_pass_p90: 'Prog pass', prog_carry_p90: 'P. carry',
  pass_completion: 'Pass %', pass_comp_pressure: 'Pass% pr.',
  pass_forward_share: 'Forward %', pass_long_share: 'Long %',
  touch_final_third: 'Final 3rd', aerial_win: 'Aerials',
}

// nombre completo para el tooltip y la tabla, donde si cabe
export const LABEL_FULL: Record<string, string> = {
  interception_p90: 'Interceptions', clearance_p90: 'Clearances',
  prog_pass_p90: 'Progressive passes', prog_carry_p90: 'Progressive carries',
  pass_completion: 'Pass completion',
  pass_comp_pressure: 'Pass completion under pressure',
  pass_forward_share: 'Forward pass share', pass_long_share: 'Long pass share',
  touch_final_third: 'Touches in final third', aerial_win: 'Aerial duels won',
  pass_p90: 'Passes', shot_p90: 'Shots', dribble_p90: 'Dribbles',
  pressure_p90: 'Pressures', carry_p90: 'Carries',
  ball_receipt_p90: 'Ball receipts', duel_p90: 'Duels',
}
