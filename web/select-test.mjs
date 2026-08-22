import assert from 'node:assert'
import { decidirSeleccion } from './src/select.ts'

const api = 'http://localhost:8000'
const buscar = async q => (await fetch(`${api}/players?q=${encodeURIComponent(q)}&limit=8`)).json()

const messi = (await buscar('Messi'))[0]
const busq  = (await buscar('Busquets'))[0]
const varios = await buscar('Sergio')
let ok = 0, fail = 0
const t = (nombre, real, esperado) => {
  try { assert.deepStrictEqual(real, esperado); ok++; console.log(`  PASA  ${nombre}`) }
  catch {
    fail++
    console.log(`  FALLA ${nombre}\n        esperado ${JSON.stringify(esperado)}\n        obtuve   ${JSON.stringify(real)}`)
  }
}

t('arranque sin referencia -> elige el primero',
  decidirSeleccion([messi], 'Messi', null)?.id, messi.id)

t('nombre completo con 1 resultado -> cambia (EL FALLO REPORTADO)',
  decidirSeleccion([busq], 'Sergio Busquets i Burgos', messi)?.id, busq.id)

t('elegir del datalist (texto exacto) entre varios -> cambia',
  decidirSeleccion(varios, varios[2].name, messi)?.id, varios[2].id)

t('busqueda ambigua -> no cambia solo, que elija la persona',
  decidirSeleccion(varios, 'Sergio', messi), null)

t('el mismo jugador ya seleccionado -> no re-elige',
  decidirSeleccion([messi], 'Messi', messi), null)

t('sin resultados -> no toca nada',
  decidirSeleccion([], 'zzzz', messi), null)

t('mayusculas y espacios sobrantes -> tolera',
  decidirSeleccion([busq], '  SERGIO BUSQUETS I BURGOS ', messi)?.id, busq.id)

console.log(`\n${ok} pasan, ${fail} fallan`)
process.exit(fail ? 1 : 0)
