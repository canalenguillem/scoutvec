import { render } from './.ssrcheck/ssr-entry.js'

const meta = await (await fetch('http://localhost:8000/meta')).json()
const prof = await (await fetch('http://localhost:8000/compare?ids=5503,5211,5487')).json()
const svg = render(meta.features, prof, ['#2a78d6', '#eb6834', '#1baf7a'])

// 1) el viewBox debe contener toda la geometria dibujada
const vb = svg.match(/viewBox="(-?[\d.]+) (-?[\d.]+) ([\d.]+) ([\d.]+)"/).slice(1).map(Number)
const [vx, vy, vw, vh] = vb
const nums = [...svg.matchAll(/(?:cx|cy|x1|y1|x2|y2|x|y)="(-?[\d.]+)"/g)].map(m => +m[1])
const puntos = [...svg.matchAll(/points="([^"]+)"/g)]
  .flatMap(m => m[1].split(' ').flatMap(p => p.split(',').map(Number)))
const todos = [...nums, ...puntos].filter(Number.isFinite)
console.log(`viewBox  x[${vx}, ${vx + vw}]  y[${vy}, ${vy + vh}]`)
console.log(`geometria  min ${Math.min(...todos).toFixed(1)}  max ${Math.max(...todos).toFixed(1)}`)
console.log(Math.min(...todos) >= vx && Math.max(...todos) <= vx + vw
  ? '  OK: nada se sale del viewBox' : '  FALLO: hay geometria fuera del viewBox')

// 2) colision de etiquetas: caja aproximada por longitud del texto
const labels = [...svg.matchAll(/<text[^>]*x="(-?[\d.]+)"[^>]*y="(-?[\d.]+)"[^>]*text-anchor="(\w+)"[^>]*>([^<]+)</g)]
  .map(([, x, y, a, t]) => {
    const w = t.length * 5.6, h = 11
    const cx = a === 'middle' ? +x : a === 'start' ? +x + w / 2 : +x - w / 2
    return { t, x0: cx - w / 2, x1: cx + w / 2, y0: +y - h / 2, y1: +y + h / 2 }
  })
console.log(`\netiquetas: ${labels.length}`)
let ch = 0
for (let i = 0; i < labels.length; i++)
  for (let j = i + 1; j < labels.length; j++) {
    const a = labels[i], b = labels[j]
    if (a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1) {
      console.log(`  COLISION: "${a.t}" x "${b.t}"`); ch++
    }
  }
console.log(ch ? `  ${ch} colisiones` : '  OK: sin solapes')

// 2b) el TEXTO de la etiqueta debe caber, no solo su punto de anclaje
const lx0 = Math.min(...labels.map(l => l.x0)), lx1 = Math.max(...labels.map(l => l.x1))
console.log(`  extension del texto x[${lx0.toFixed(1)}, ${lx1.toFixed(1)}]`)
console.log(lx0 >= vx && lx1 <= vx + vw
  ? '  OK: el texto cabe en el viewBox'
  : `  FALLO: el texto se sale (margen ${(vx - lx0).toFixed(1)} / ${(lx1 - vx - vw).toFixed(1)})`)

// 3) el texto no debe llevar color de serie
const coloreado = [...svg.matchAll(/<text[^>]*fill="(#[0-9a-f]{6})"/gi)]
console.log(`\ntexto con color de serie: ${coloreado.length ? 'FALLO ' + coloreado.map(m=>m[1]) : 'OK: ninguno'}`)
console.log(`series dibujadas: ${(svg.match(/stroke-width="2"/g) || []).length} poligonos a 2px`)
console.log(`marcadores: r=4 con anillo de superficie -> ${(svg.match(/r="4"/g) || []).length}`)
