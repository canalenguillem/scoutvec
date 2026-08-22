import { useEffect, useRef, useState } from 'react'
import Radar from './Radar'
import { LABEL_FULL, NoAutenticado, ask, compare, getMeta, getSimilar,
         logout, me, searchPlayers } from './api'
import { CambiarClave, Login } from './Auth'
import { decidirSeleccion } from './select'
import type { AskResponse, Meta, Neighbour, Player, Profile, Session } from './types'

// slots categoricos en orden fijo, nunca ciclados. Validados con
// scripts/validate_palette.js en claro y oscuro.
const COLORS = ['var(--series-1)', 'var(--series-2)',
                'var(--series-3)', 'var(--series-4)']
const MAX_CMP = 4

export default function App() {
  // 'cargando' hasta saber si hay sesion; null = anonimo
  const [sesion, setSesion] = useState<Session | null | 'cargando'>('cargando')

  useEffect(() => { me().then(setSesion).catch(() => setSesion(null)) }, [])

  if (sesion === 'cargando') {
    return <main className="wrap"><p className="muted">Loading…</p></main>
  }
  if (!sesion) return <Login onEntra={setSesion} />
  if (sesion.must_change_password) {
    return <CambiarClave sesion={sesion} onCambiada={setSesion} />
  }
  return <Explorer sesion={sesion} alSalir={() => setSesion(null)} />
}

function Explorer({ sesion, alSalir }:
                  { sesion: Session; alSalir: () => void }) {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [dataset, setDataset] = useState<string | undefined>(undefined)
  const [q, setQ] = useState('Messi')
  const [hits, setHits] = useState<Player[]>([])
  const [anchor, setAnchor] = useState<Player | null>(null)   // referencia
  const [neighbours, setNeighbours] = useState<Neighbour[]>([])
  const [picked, setPicked] = useState<number[]>([])          // ids en el radar
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [k, setK] = useState(8)
  const [league, setLeague] = useState('')
  const [role, setRole] = useState('')
  const [sameRole, setSameRole] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [view, setView] = useState<'chart' | 'table'>('chart')
  const [pregunta, setPregunta] = useState('')
  const [respuesta, setRespuesta] = useState<AskResponse | null>(null)
  const [pensando, setPensando] = useState(false)
  const panelRespuesta = useRef<HTMLElement | null>(null)

  // los resultados vienen de la consulta en lenguaje natural si la hay,
  // y si no del jugador de referencia
  const resultados: Neighbour[] = respuesta ? respuesta.results : neighbours

  // si la sesion caduca a media navegacion hay que volver al login, no
  // pintar un error que el usuario no puede resolver
  const fallo = (e: unknown) => {
    if (e instanceof NoAutenticado) alSalir()
    else setErr(e instanceof Error ? e.message : String(e))
  }

  useEffect(() => {
    getMeta(dataset).then(m => { setMeta(m); setDataset(m.dataset) }).catch(fallo)
  }, [dataset])

  // buscar segun se escribe, con un respiro para no disparar en cada tecla
  useEffect(() => {
    const t = setTimeout(() => {
      searchPlayers(q, { limit: 8, dataset }).then(setHits).catch(fallo)
    }, 200)
    return () => clearTimeout(t)
  }, [q, dataset])

  // Elegir solo cuando la busqueda es inequivoca: al arrancar, cuando queda
  // un unico resultado, o cuando el texto coincide exacto con un nombre —que
  // es lo que produce elegir en el datalist—. Sin esto, escribir un nombre
  // completo deja 1 resultado, oculta los chips y no hay forma de
  // seleccionarlo. Depende solo de [hits] a proposito: con [q] en las
  // dependencias correria con hits del tiron anterior.
  useEffect(() => {
    const elegido = decidirSeleccion(hits, q, anchor)
    if (elegido) choose(elegido)
  }, [hits])

  useEffect(() => {
    if (!anchor) return
    getSimilar(anchor.id, { k, role: role || undefined, sameRole,
                            league: league || undefined, dataset })
      .then(setNeighbours).catch(fallo)
  }, [anchor, k, role, sameRole, league, dataset])

  useEffect(() => {
    if (!picked.length) { setProfiles([]); return }
    compare(picked, dataset).then(setProfiles).catch(fallo)
  }, [picked])

  function choose(p: Player) {
    setAnchor(p)
    setPicked([p.id])
    setRespuesta(null)      // volver al modo jugador-de-referencia
    setErr(null)
  }

  async function preguntar(e: React.FormEvent) {
    e.preventDefault()
    if (!pregunta.trim() || pensando) return
    setPensando(true)
    setErr(null)
    try {
      const r = await ask(pregunta, dataset)
      setRespuesta(r)
      // el radar necesita al menos un perfil para no quedarse vacio
      setPicked(r.results.length ? [r.results[0].id] : [])
      // en movil la respuesta nace fuera de la pantalla; sin esto parece
      // que no ha pasado nada
      requestAnimationFrame(() =>
        panelRespuesta.current?.scrollIntoView({ behavior: 'smooth',
                                                 block: 'start' }))
    } catch (e) {
      fallo(e)
    } finally {
      setPensando(false)
    }
  }

  function toggle(id: number) {
    setPicked(prev => prev.includes(id)
      ? (prev.length > 1 ? prev.filter(x => x !== id) : prev)
      : (prev.length < MAX_CMP ? [...prev, id] : prev))
  }

  const activo = meta?.datasets.find(d => d.slug === dataset)

  if (err) return <main className="wrap"><p className="error">Error: {err}
    <br /><small>Is the API running? <code>uvicorn scoutvec.api:app</code></small>
  </p></main>

  if (!meta) return <main className="wrap"><p className="muted">Loading…</p></main>

  return (
    <main className="wrap">
      <header>
        <div className="topbar">
          <h1>scoutvec</h1>
          <span className="muted small">
            {sesion.username}
            {' · '}
            <button type="button" className="linkish"
                    onClick={() => { logout().finally(alSalir) }}>
              sign out
            </button>
          </span>
        </div>
        <p className="muted">
          Style similarity across {meta.players.toLocaleString()} outfield
          players — {meta.leagues.join(', ')}
          {activo && <>, {activo.season}</>}. Position is not in the vector.
        </p>
      </header>

      {meta.datasets.length > 1 && (
        <section className="datasets" aria-label="Dataset">
          {meta.datasets.map(d => (
            <button key={d.slug} type="button" title={d.note}
                    className={d.slug === dataset ? 'chip on' : 'chip'}
                    onClick={() => {
                      if (d.slug === dataset) return
                      // otro dataset es otro espacio: nada de lo elegido sirve
                      setDataset(d.slug); setMeta(null); setAnchor(null)
                      setRespuesta(null); setPicked([]); setProfiles([])
                      setNeighbours([]); setLeague(''); setQ('')
                    }}>
              {d.label} <span className="muted">{d.season}</span>
            </button>
          ))}
        </section>
      )}

      <form className="ask" onSubmit={preguntar}>
        <label htmlFor="ask-input">Ask in plain language</label>
        <div className="ask-row">
          <input id="ask-input" value={pregunta} disabled={pensando}
                 onChange={e => setPregunta(e.target.value)}
                 placeholder="a centre-back who plays out from the back and wins headers" />
          <button type="submit" disabled={pensando || !pregunta.trim()}>
            {pensando ? 'Thinking…' : 'Ask'}
          </button>
        </div>
      </form>

      {!respuesta && <section className="controls" aria-label="Filters">
        <label>Player
          <input value={q} onChange={e => setQ(e.target.value)}
                 placeholder="Search a name…" list="hits" />
          <datalist id="hits">
            {hits.map(h => <option key={h.id} value={h.name} />)}
          </datalist>
        </label>
        <label>League
          <select value={league} onChange={e => setLeague(e.target.value)}>
            <option value="">Any</option>
            {meta.leagues.map(l => <option key={l}>{l}</option>)}
          </select>
        </label>
        <label>Role
          <select value={role} onChange={e => setRole(e.target.value)}
                  disabled={sameRole}>
            <option value="">Any</option>
            {meta.roles.map(r => <option key={r}>{r}</option>)}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={sameRole}
                 onChange={e => setSameRole(e.target.checked)} />
          Same role as query
        </label>
        <label>Results {k}
          <input type="range" min="3" max="20" value={k}
                 onChange={e => setK(Number(e.target.value))} />
        </label>
      </section>}

      {!respuesta && hits.length > 0 && (
        <section className="hits" aria-label="Search results">
          {hits.slice(0, 6).map(h => (
            <button key={h.id} onClick={() => choose(h)}
                    className={anchor?.id === h.id ? 'chip on' : 'chip'}>
              {h.name}
            </button>
          ))}
        </section>
      )}

      {anchor && (
        <div className="split">
          <section aria-label="Nearest neighbours" ref={panelRespuesta}>
            {respuesta?.query.unsupported ? (
              // decirlo, en vez de devolver lo mas parecido y callar
              <>
                <h2>Can't answer that</h2>
                <p className="unsupported">{respuesta.query.unsupported}</p>
                <p className="muted small">
                  The space holds 17 event-derived dimensions for outfield
                  players only. Describe how someone plays — passing, pressing,
                  carrying, aerials — rather than who they are.
                </p>
              </>
            ) : respuesta ? (
              <>
                <h2>{resultados.length} players</h2>
                <p className="muted small">
                  {respuesta.query.summary}
                  {respuesta.query.role && <> · role {respuesta.query.role}</>}
                  {respuesta.query.league && <> · {respuesta.query.league}</>}
                </p>
              </>
            ) : (
              <>
                <h2>Nearest to {anchor.name}</h2>
                <p className="muted small">
                  {anchor.team} · {anchor.league} · {anchor.role} ·
                  {' '}{anchor.minutes.toLocaleString()} min
                </p>
              </>
            )}
            <ol className="neighbours">
              {resultados.map(n => {
                const at = picked.indexOf(n.id)
                return (
                  <li key={n.id}>
                    <button onClick={() => toggle(n.id)}
                            className={at >= 0 ? 'row on' : 'row'}
                            aria-pressed={at >= 0}>
                      <span className="swatch" style={{
                        background: at >= 0 ? COLORS[at] : 'transparent',
                        borderColor: at >= 0 ? COLORS[at] : 'var(--border)',
                      }} />
                      <span className="sim">{n.sim.toFixed(3)}</span>
                      <span className="name">{n.name}</span>
                      <span className="meta">{n.team} · {n.role}</span>
                    </button>
                  </li>
                )
              })}
              {!resultados.length && <li className="muted small">
                No players match.</li>}
            </ol>

            {respuesta && !respuesta.query.unsupported && (
              <details className="why" open>
                <summary>Why these players</summary>
                {/* el perfil se deriva de estos ajustes, asi que el texto
                    no puede describir un movimiento que no ocurrio */}
                <ul className="adjustments">
                  {respuesta.query.adjustments.map(a => (
                    <li key={a.feature}>
                      <code>{LABEL_FULL[a.feature] ?? a.feature}</code>
                      <b>{Math.round(a.value * 100)}</b>
                      <span className="muted">{a.why}</span>
                    </li>
                  ))}
                  {!respuesta.query.adjustments.length &&
                    <li className="muted">No dimension was adjusted.</li>}
                </ul>
                <p className="muted small">
                  Everything not listed sits at the 50th percentile.
                  {' '}Translated by {respuesta.query.model}.
                </p>
              </details>
            )}

            {respuesta && (
              <button type="button" className="linkish"
                      onClick={() => setRespuesta(null)}>
                ← back to player search
              </button>
            )}
          </section>

          <section aria-label="Profile comparison">
            <div className="head">
              <h2>Profile</h2>
              <div className="toggle" role="group" aria-label="View">
                <button onClick={() => setView('chart')}
                        className={view === 'chart' ? 'on' : ''}>Chart</button>
                <button onClick={() => setView('table')}
                        className={view === 'table' ? 'on' : ''}>Table</button>
              </div>
            </div>

            {/* leyenda siempre presente: la identidad nunca es solo el color */}
            <ul className="legend">
              {profiles.map((p, i) => (
                <li key={p.id}>
                  <span className="dot" style={{ background: COLORS[i] }} />
                  {p.name} <span className="muted">({p.role})</span>
                </li>
              ))}
            </ul>

            {view === 'chart'
              ? <Radar features={meta.features} players={profiles} colors={COLORS} />
              : <ProfileTable features={meta.features} players={profiles} />}

            <p className="muted small">
              Click any neighbour to add it to the comparison (up to {MAX_CMP}).
            </p>
          </section>
        </div>
      )}
    </main>
  )
}

function ProfileTable({ features, players }: { features: string[]; players: Profile[] }) {
  return (
    <div className="table-scroll">
      <table>
        <caption className="visually-hidden">
          Percentile by metric for the selected players
        </caption>
        <thead>
          <tr>
            <th scope="col">Metric</th>
            {players.map(p => <th key={p.id} scope="col">{p.name.split(' ').pop()}</th>)}
          </tr>
        </thead>
        <tbody>
          {features.map(f => (
            <tr key={f}>
              <th scope="row">{LABEL_FULL[f] ?? f}</th>
              {players.map(p => (
                <td key={p.id}>{Math.round((p.vector[f] ?? 0) * 100)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
