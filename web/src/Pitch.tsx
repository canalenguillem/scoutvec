import { LABEL_FULL } from './api'
import type { PitchEvent } from './types'

// Campo de StatsBomb: 120x80 yardas, el equipo siempre ataca hacia x=120.
// Las coordenadas llegan ya en ese sistema, asi que no hay que transformar
// nada — solo voltear la y, porque en SVG crece hacia abajo.
const L = 120
const W = 80
const M = 3

const fy = (y: number) => W - y

function Marcas() {
  return (
    <g className="pitch-lines">
      <rect x="0" y="0" width={L} height={W} rx="0.5" />
      <line x1={L / 2} y1="0" x2={L / 2} y2={W} />
      <circle cx={L / 2} cy={W / 2} r="10" />
      <circle cx={L / 2} cy={W / 2} r="0.6" className="pitch-spot" />
      {/* areas: grande 18 yardas, pequeña 6 */}
      <rect x="0" y={fy(62)} width="18" height="44" />
      <rect x={L - 18} y={fy(62)} width="18" height="44" />
      <rect x="0" y={fy(50)} width="6" height="20" />
      <rect x={L - 6} y={fy(50)} width="6" height="20" />
      <circle cx="12" cy={W / 2} r="0.6" className="pitch-spot" />
      <circle cx={L - 12} cy={W / 2} r="0.6" className="pitch-spot" />
    </g>
  )
}

interface Props {
  events: PitchEvent[]
  shape: 'flecha' | 'punto'
  color: string
  name: string
  feature: string
  label: string
}

export default function Pitch({ events, shape, color, name, feature, label }: Props) {
  return (
    <figure className="pitch-figure">
      <figcaption className="pitch-title">
        <span className="dot" style={{ background: color }} /> {name}
        <span className="muted"> · {events.length} {label.toLowerCase()}</span>
      </figcaption>
      <svg viewBox={`${-M} ${-M} ${L + M * 2} ${W + M * 2}`} className="pitch"
           role="img"
           aria-label={`${label} by ${name}, ${events.length} shown, attacking left to right`}>
        <Marcas />
        {shape === 'flecha'
          ? events.map((e, n) => (
              <line key={n} x1={e.x} y1={fy(e.y)} x2={e.end_x} y2={fy(e.end_y!)}
                    stroke={color} strokeWidth="0.35" strokeOpacity="0.5"
                    strokeLinecap="round" />
            ))
          : events.map((e, n) => (
              <circle key={n} cx={e.x} cy={fy(e.y)} r="0.9"
                      fill={color} fillOpacity="0.55" />
            ))}
      </svg>
      <p className="muted small pitch-note">
        {LABEL_FULL[feature] ?? feature} · attacking left to right
      </p>
    </figure>
  )
}
