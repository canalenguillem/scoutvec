import { useState } from 'react'
import { changePassword, login } from './api'
import type { Session } from './types'

/** Pantalla de acceso. Sin registro: los usuarios los crea el seed. */
export function Login({ onEntra }: { onEntra: (s: Session) => void }) {
  const [usuario, setUsuario] = useState('')
  const [clave, setClave] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    if (enviando) return
    setEnviando(true)
    setErr(null)
    try {
      onEntra(await login(usuario, clave))
    } catch (e) {
      // el backend no distingue usuario inexistente de clave mala, y el
      // mensaje tampoco debe hacerlo
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <main className="wrap gate">
      <h1>scoutvec</h1>
      <p className="muted">Player style similarity. Sign in to continue.</p>
      <form onSubmit={enviar} className="gate-form">
        <label>Username
          <input value={usuario} autoComplete="username" autoFocus
                 onChange={e => setUsuario(e.target.value)} />
        </label>
        <label>Password
          <input type="password" value={clave} autoComplete="current-password"
                 onChange={e => setClave(e.target.value)} />
        </label>
        {err && <p className="error small">{err}</p>}
        <button type="submit" disabled={enviando || !usuario || !clave}>
          {enviando ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}

/** Obligatoria en el primer acceso: la clave inicial es temporal. */
export function CambiarClave({ sesion, onCambiada }:
  { sesion: Session; onCambiada: (s: Session) => void }) {
  const [actual, setActual] = useState('')
  const [nueva, setNueva] = useState('')
  const [repite, setRepite] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)

  const corta = nueva.length > 0 && nueva.length < 10
  const distintas = repite.length > 0 && nueva !== repite

  async function enviar(e: React.FormEvent) {
    e.preventDefault()
    if (enviando || corta || distintas || !nueva) return
    setEnviando(true)
    setErr(null)
    try {
      onCambiada(await changePassword(actual, nueva))
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setEnviando(false)
    }
  }

  return (
    <main className="wrap gate">
      <h1>Choose a password</h1>
      <p className="muted">
        Signed in as <b>{sesion.username}</b>. The password you were given is
        temporary and has to be replaced before you can use the app.
      </p>
      <form onSubmit={enviar} className="gate-form">
        <label>Temporary password
          <input type="password" value={actual} autoComplete="current-password"
                 autoFocus onChange={e => setActual(e.target.value)} />
        </label>
        <label>New password
          <input type="password" value={nueva} autoComplete="new-password"
                 onChange={e => setNueva(e.target.value)} />
        </label>
        <label>Repeat new password
          <input type="password" value={repite} autoComplete="new-password"
                 onChange={e => setRepite(e.target.value)} />
        </label>
        <p className={corta ? 'error small' : 'muted small'}>
          At least 10 characters.
        </p>
        {distintas && <p className="error small">The two do not match.</p>}
        {err && <p className="error small">{err}</p>}
        <button type="submit"
                disabled={enviando || !actual || !nueva || corta || distintas}>
          {enviando ? 'Saving…' : 'Set password'}
        </button>
      </form>
    </main>
  )
}
