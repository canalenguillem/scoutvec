// solo para pruebas: renderiza el campo en servidor y devuelve el SVG
import { renderToStaticMarkup } from 'react-dom/server'
import Pitch from './Pitch'
import type { PitchEvent } from './types'

export function render(events: PitchEvent[], shape: 'flecha' | 'punto') {
  return renderToStaticMarkup(
    <Pitch events={events} shape={shape} color="#2a78d6" name="Test"
           feature="prog_pass_p90" label="Progressive passes" />)
}
