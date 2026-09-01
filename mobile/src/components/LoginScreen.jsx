import { useState } from 'react'
import { login } from '../api.js'

export default function LoginScreen({ onLoggedIn }) {
  const [usr, setUsr] = useState('')
  const [pwd, setPwd] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      await login(usr, pwd)
      onLoggedIn()
    } catch (err) {
      setError(err.message || 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={handleSubmit}>
        <h1>Purchase Entry</h1>
        <p className="subtitle">Sign in with your ERP account</p>

        <label htmlFor="usr">Username / Email</label>
        <input
          id="usr"
          type="text"
          value={usr}
          onChange={(e) => setUsr(e.target.value)}
          autoCapitalize="none"
          autoCorrect="off"
          required
        />

        <label htmlFor="pwd">Password</label>
        <input
          id="pwd"
          type="password"
          value={pwd}
          onChange={(e) => setPwd(e.target.value)}
          required
        />

        {error && <div className="error-banner">{error}</div>}

        <button type="submit" className="primary-btn" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign In'}
        </button>
      </form>
    </div>
  )
}
