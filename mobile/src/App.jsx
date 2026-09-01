import { useState, useEffect } from 'react'
import LoginScreen from './components/LoginScreen.jsx'
import TabBar from './components/TabBar.jsx'
import NewPurchase from './components/NewPurchase.jsx'
import StockList from './components/StockList.jsx'
import { checkSession, logout } from './api.js'

export default function App() {
  const [authState, setAuthState] = useState('checking') // checking | loggedOut | loggedIn
  const [tab, setTab] = useState('purchase')

  useEffect(() => {
    checkSession().then((ok) => setAuthState(ok ? 'loggedIn' : 'loggedOut'))
  }, [])

  if (authState === 'checking') {
    return <div className="splash">Loading…</div>
  }

  if (authState === 'loggedOut') {
    return <LoginScreen onLoggedIn={() => setAuthState('loggedIn')} />
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <span>Purchase Entry</span>
        <button
          type="button"
          className="link-btn"
          onClick={async () => {
            await logout()
            setAuthState('loggedOut')
          }}
        >
          Log out
        </button>
      </header>

      <main className="app-main">
        {tab === 'purchase' ? <NewPurchase /> : <StockList />}
      </main>

      <TabBar active={tab} onChange={setTab} />
    </div>
  )
}
