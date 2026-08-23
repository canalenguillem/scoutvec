import { render } from './.ssrcheck/ssr-pitch.js'

// eventos en las cuatro esquinas y el centro, para comprobar el mapeo
const ev = [
  { x: 0,   y: 0,  end_x: 10,  end_y: 10 },
  { x: 120, y: 80, end_x: 110, end_y: 70 },
  { x: 60,  y: 40, end_x: 90,  end_y: 40 },
]
const svg = render(ev, 'flecha')
const [vx, vy, vw, vh] = svg.match(/viewBox="(-?[\d.]+) (-?[\d.]+) ([\d.]+) ([\d.]+)"/).slice(1).map(Number)
console.log(`viewBox x[${vx}, ${vx + vw}]  y[${vy}, ${vy + vh}]`)

const nums = [...svg.matchAll(/(?:cx|cy|x1|y1|x2|y2|x|y)="(-?[\d.]+)"/g)].map(m => +m[1])
const fuera = nums.filter(n => n < Math.min(vx, vy) || n > Math.max(vx + vw, vy + vh))
console.log(fuera.length ? `  FALLO: ${fuera.length} coordenadas fuera` : '  OK: todo dentro del viewBox')

// la y se voltea: y=0 (banda inferior de StatsBomb) debe salir en la parte baja del SVG
const l = [...svg.matchAll(/<line[^>]*x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)"[^>]*stroke="#/g)]
console.log(`  lineas de datos dibujadas: ${l.length} (esperadas ${ev.length})`)
const [, x1, y1] = l[0]
console.log(+x1 === 0 && +y1 === 80 ? '  OK: y volteada (y=0 -> abajo del SVG)' : `  revisar: (${x1},${y1})`)

// el campo debe ser contexto, no dato
console.log(svg.includes('class="pitch-lines"') ? '  OK: lineas del campo con clase propia' : '  FALLO')
console.log(/stroke="#2a78d6"/.test(svg) ? '  OK: los eventos llevan el color de serie' : '  FALLO')
const puntos = render([{x:60,y:40}], 'punto')
console.log(/<circle[^>]*fill="#2a78d6"/.test(puntos) ? '  OK: forma punto dibuja circulos' : '  FALLO')
