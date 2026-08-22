import type { Player } from './types'

/**
 * Decide que jugador debe pasar a ser la referencia tras una busqueda.
 *
 * Vive aparte del componente para poder probarlo sin navegador, que es como
 * se encontro el fallo original: escribir un nombre completo dejaba un solo
 * resultado, los chips se ocultaban y no habia forma de seleccionarlo.
 *
 * Devuelve el jugador a elegir, o null si hay que dejar la seleccion como
 * esta (busqueda ambigua: que elija la persona).
 */
export function decidirSeleccion(
  hits: Player[],
  q: string | null | undefined,
  anchor: Player | null,
): Player | null {
  if (!hits.length) return null
  if (!anchor) return hits[0]              // arranque: no dejar la app vacia
  const texto = (q ?? '').trim().toLowerCase()
  const exacto = hits.find(h => h.name.toLowerCase() === texto)
  const elegido = exacto ?? (hits.length === 1 ? hits[0] : null)
  return elegido && elegido.id !== anchor.id ? elegido : null
}
