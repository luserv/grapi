"use client"
import { useState } from "react"

interface Props {
  loginError: string
  isLoggingIn: boolean
  needsTwofa: boolean
  onLogin: (params: { username: string; password: string; twofa: string }) => void
}

export default function LoginCard({ loginError, isLoggingIn, needsTwofa, onLogin }: Props) {
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [twofa, setTwofa]       = useState("")

  function submit() {
    onLogin({ username, password, twofa })
    if (!loginError) setPassword("")
  }

  const onEnter = (e: React.KeyboardEvent) => { if (e.key === "Enter") submit() }

  return (
    <div className="card">
      <h1>Instagram Followers Analyzer</h1>

      <div className="field">
        <span className="field-label">Usuario</span>
        <input type="text" placeholder="tu_usuario" autoComplete="username"
          value={username} onChange={e => setUsername(e.target.value)} onKeyDown={onEnter} />
      </div>

      <div className="field">
        <span className="field-label">Contraseña</span>
        <input type="password" placeholder="••••••••" autoComplete="current-password"
          value={password} onChange={e => setPassword(e.target.value)} onKeyDown={onEnter} />
      </div>

      {needsTwofa && (
        <div className="field">
          <span className="field-label">Código 2FA</span>
          <input type="text" placeholder="123456" maxLength={8}
            value={twofa} onChange={e => setTwofa(e.target.value)} onKeyDown={onEnter} />
        </div>
      )}

      <div className="error-msg">{loginError}</div>

      <div className="field">
        <button className="btn-primary" disabled={isLoggingIn} onClick={submit}>
          {isLoggingIn ? "Conectando..." : "Iniciar sesión"}
        </button>
      </div>
    </div>
  )
}
