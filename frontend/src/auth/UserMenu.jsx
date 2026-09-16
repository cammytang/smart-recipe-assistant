import { useAuth } from './context'
export default function UserMenu() {
  const { session, status, user, logoutBusy } = useAuth()
  if (status === 'checking') return <span className="auth-check" role="status">正在检查登录…</span>
  if (status === 'error') return <button className="auth-entry" onClick={() => session.check()}>连接失败 · 重试</button>
  if (!user) return <button className="auth-entry" onClick={() => session.openLogin()}>登录</button>
  return <button className="auth-avatar" aria-label={`${user.username}的用户画像`} disabled={logoutBusy} onClick={() => { session.patch({ drawer: true, error: '' }); session.loadProfile() }}>{user.username[0].toUpperCase()}</button>
}
