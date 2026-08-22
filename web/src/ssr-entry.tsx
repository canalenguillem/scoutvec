// entrada solo para pruebas: renderiza el radar en servidor y devuelve el SVG
import { renderToStaticMarkup } from 'react-dom/server'
import Radar from './Radar'
import type { Profile } from './types'

export function render(features: string[], players: Profile[], colors: string[]) {
  return renderToStaticMarkup(
    <Radar features={features} players={players} colors={colors} />)
}
