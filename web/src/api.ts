import type { AskResponse, Meta, Neighbour, Player, Profile, Session, SimilarOpts } from './types'

const base = '/api'

/** Se lanza cuando no hay sesion, para que App muestre el login sin
 *  confundirlo con un error de red. */
export class NoAutenticado extends Error {}

/** Se lanza cuando la sesion es valida pero la clave sigue siendo temporal. */
export class DebeCambiarClave extends Error {}

function comprobar(status: number): void {
  if (status === 401) throw new NoAutenticado('sin sesion')
  if (status === 403) throw new DebeCambiarClave('debes cambiar la contraseña')
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(base + path)
  comprobar(r.status)
  if (!r.ok) throw new Error(`${r.status} ${await detalleDe(r)}`)
  return r.json() as Promise<T>
}

async function detalleDe(r: Response): Promise<string> {
  try {
    return (await r.json()).detail ?? r.statusText
  } catch {
    return r.statusText
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(base + path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(await detalleDe(r))
  return r.json() as Promise<T>
}

export const login = (username: string, password: string) =>
  post<Session>('/auth/login', { username, password })

export const logout = () => post<{ status: string }>('/auth/logout', {})

export const changePassword = (current_password: string, new_password: string) =>
  post<Session>('/auth/change-password', { current_password, new_password })

export async function me(): Promise<Session | null> {
  const r = await fetch(`${base}/auth/me`)
  if (r.status === 401) return null
  if (!r.ok) throw new Error(await detalleDe(r))
  return r.json() as Promise<Session>
}

// el dataset viaja en todas las llamadas: cada uno es un espacio vectorial
// distinto y sus player_id no son intercambiables
export const getMeta = (dataset?: string) =>
  get<Meta>(`/meta${dataset ? `?dataset=${encodeURIComponent(dataset)}` : ''}`)

export const searchPlayers = (
  q: string,
  { league, role, limit = 30, dataset }:
    { league?: string; role?: string; limit?: number; dataset?: string } = {},
) => {
  const p = new URLSearchParams({ limit: String(limit) })
  if (q) p.set('q', q)
  if (league) p.set('league', league)
  if (role) p.set('role', role)
  if (dataset) p.set('dataset', dataset)
  return get<Player[]>(`/players?${p}`)
}

export const getPlayer = (id: number) => get<Profile>(`/players/${id}`)

export const getSimilar = (
  id: number,
  { k = 8, role, sameRole, league, dataset }: SimilarOpts = {},
) => {
  const p = new URLSearchParams({ k: String(k) })
  if (role) p.set('role', role)
  if (sameRole) p.set('same_role', 'true')
  if (league) p.set('league', league)
  if (dataset) p.set('dataset', dataset)
  return get<Neighbour[]>(`/similar/${id}?${p}`)
}

export const compare = (ids: number[], dataset?: string) =>
  get<Profile[]>(`/compare?ids=${ids.join(',')}` +
                 (dataset ? `&dataset=${encodeURIComponent(dataset)}` : ''))

export async function ask(q: string, dataset?: string): Promise<AskResponse> {
  const r = await fetch(`${base}/ask` +
                        (dataset ? `?dataset=${encodeURIComponent(dataset)}` : ''), {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ q }),
  })
  comprobar(r.status)
  if (!r.ok) throw new Error(`${r.status} ${await detalleDe(r)}`)
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
