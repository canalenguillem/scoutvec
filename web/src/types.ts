export type Role = 'CB' | 'FB' | 'DM' | 'CM' | 'W' | 'FW'

export interface Player {
  id: number
  name: string
  team: string
  league: string
  role: Role
  minutes: number
}

/** Un jugador con su vector: percentil [0,1] por metrica. */
export interface Profile extends Player {
  vector: Record<string, number>
}

/** Un vecino es un jugador mas su similitud coseno con la consulta. */
export interface Neighbour extends Player {
  sim: number
}

export interface Meta {
  features: string[]
  roles: Role[]
  leagues: string[]
  teams: string[]
  players: number
}

export interface SimilarOpts {
  k?: number
  role?: string
  sameRole?: boolean
  league?: string
}

export interface Adjustment {
  feature: string
  value: number
  why: string
}

/** Lo que el modelo pidio, devuelto junto a los resultados para que la
 *  respuesta sea auditable: si los jugadores no convencen, se ve por que. */
export interface StructuredQuery {
  adjustments: Adjustment[]
  profile: Record<string, number>
  role: string | null
  league: string | null
  k: number
  summary: string
  model: string
  prompt_version: string
}

export interface AskResponse {
  query: StructuredQuery
  results: Neighbour[]
}
