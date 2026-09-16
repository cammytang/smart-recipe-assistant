import { useEffect, useState, useSyncExternalStore } from 'react'
import { Session } from './session'
import { apiFetch } from '../api/client'
import { AuthContext } from './context'
import AuthDialog from './AuthDialog'
import ProfileDrawer from './ProfileDrawer'
import './auth.css'

export default function AuthProvider({ children }) {
  const [session] = useState(() => new Session(apiFetch))
  const state = useSyncExternalStore(session.subscribe, session.snapshot)
  useEffect(() => {
    session.check()
    const channel = typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel('recipe-auth')
    session.setNotifier(() => channel?.postMessage('identity-changed'))
    const check = () => session.check()
    if (channel) channel.onmessage = check
    window.addEventListener('focus', check)
    return () => { channel?.close(); window.removeEventListener('focus', check); session.dispose(); session.setNotifier(() => {}) }
  }, [session])
  return <AuthContext.Provider value={{ session, ...state }}>{children}<AuthDialog /><ProfileDrawer /></AuthContext.Provider>
}
