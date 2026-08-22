import { LABEL, LABEL_FULL } from './api'
import type { Profile } from './types'

// Radar de percentiles. Ejes fijos y en el mismo orden siempre: el orden de
// un radar es arbitrario, asi que al menos debe ser ESTABLE entre jugadores,
// o comparar dos formas no significa nada.
const R = 132          // radio del area de datos
const PAD = 92         // hueco para las etiquetas
const SIZE = (R + PAD) * 2
const RINGS = [0.25, 0.5, 0.75, 1]

const pt = (ang: number, r: number): [number, number] =>
  [Math.cos(ang) * r, Math.sin(ang) * r]

interface Props {
  features: string[]
  players: Profile[]
  colors: string[]
}

export default function Radar({ features, players, colors }: Props) {
  if (!players.length) return null
  // -90deg para que el primer eje quede arriba
  const ang = (i: number) => (i / features.length) * 2 * Math.PI - Math.PI / 2

  const poly = (p: Profile) => features
    .map((f, i) => pt(ang(i), (p.vector[f] ?? 0) * R).join(','))
    .join(' ')

  return (
    <figure className="radar-figure">
      <svg viewBox={`${-SIZE / 2} ${-SIZE / 2} ${SIZE} ${SIZE}`}
           className="radar" role="img"
           aria-label={`Percentile profile of ${players.map(p => p.name).join(', ')}`}>
        {RINGS.map(t => <circle key={t} r={t * R} className="grid-ring" />)}
        {features.map((f, i) => {
          const [x, y] = pt(ang(i), R)
          return <line key={f} x1="0" y1="0" x2={x} y2={y} className="grid-spoke" />
        })}

        {players.map((p, s) => (
          <g key={p.id}>
            <polygon points={poly(p)} fill={colors[s]} fillOpacity="0.12" stroke="none" />
            <polygon points={poly(p)} fill="none" stroke={colors[s]}
                     strokeWidth="2" strokeLinejoin="round" />
            {features.map((f, i) => {
              const [x, y] = pt(ang(i), (p.vector[f] ?? 0) * R)
              return (
                <circle key={f} cx={x} cy={y} r="4" fill={colors[s]}
                        stroke="var(--surface-1)" strokeWidth="2">
                  <title>
                    {`${p.name} — ${LABEL_FULL[f] ?? f}: ${((p.vector[f] ?? 0) * 100).toFixed(0)}th pct`}
                  </title>
                </circle>
              )
            })}
          </g>
        ))}

        {/* etiquetas de eje: texto en tinta, nunca en el color de la serie */}
        {features.map((f, i) => {
          const a = ang(i)
          const [x, y] = pt(a, R + 16)
          const cos = Math.cos(a)
          const anchor = Math.abs(cos) < 0.25 ? 'middle' : cos > 0 ? 'start' : 'end'
          return (
            <text key={f} x={x} y={y} className="axis-label"
                  textAnchor={anchor} dominantBaseline="middle">
              {LABEL[f] ?? f}
            </text>
          )
        })}
        <text x="0" y={-R - 4} className="ring-label" textAnchor="middle">100</text>
        <text x="0" y={-R / 2 - 4} className="ring-label" textAnchor="middle">50</text>
      </svg>
      <figcaption>
        Global percentile within 1,419 outfield players, possession-adjusted.
        Axis order is fixed across players.
      </figcaption>
    </figure>
  )
}
