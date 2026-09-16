import { useEffect, useRef, useState } from 'react'
import { Eye, EyeOff, X } from 'lucide-react'
import { useAuth } from './context'

export default function AuthDialog() {
  const { dialog, session } = useAuth()
  return dialog ? <Dialog session={session} /> : null
}
function Dialog({ session }) {
  const ref = useRef(null)
  const [mode, setMode] = useState('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [visible, setVisible] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [cooldown, setCooldown] = useState(0)
  const locked = useRef(false)
  useEffect(() => {
    const previous = session.focusReturn || document.activeElement
    const modal = ref.current
    modal.showModal()
    modal.querySelector('#auth-username')?.focus()
    return () => { modal.close(); if (previous?.isConnected) previous.focus() }
  }, [session])
  useEffect(() => {
    if (!cooldown) return
    const timer = setTimeout(() => setCooldown(value => value - 1), 1000)
    return () => clearTimeout(timer)
  }, [cooldown])
  const switchMode = () => { setMode(mode === 'login' ? 'register' : 'login'); setPassword(''); setConfirmation(''); setError(''); setNotice('') }
  const submit = async event => {
    event.preventDefault()
    if (locked.current || cooldown) return
    const name = username.trim().toLowerCase()
    if (!/^[a-z0-9_]{3,64}$/.test(name)) { setError('用户名需为 3～64 位英文字母、数字或下划线。'); return }
    if (!/^[\x20-\x7e]{8,128}$/.test(password)) { setError('密码需为 8～128 位英文字母、数字、符号或空格，不支持中文。'); return }
    if (mode === 'register' && password !== confirmation) { setError('两次输入的密码不一致。'); return }
    locked.current = true; setBusy(true); setError(''); setNotice('')
    try {
      await session.authenticate(mode, { username: name, password })
      setPassword(''); setConfirmation('')
      if (mode === 'register') { setUsername(name); setMode('login'); setNotice('注册成功，请登录。') }
    } catch (failure) {
      setError(failure.status === 401 ? '用户名或密码错误' : failure.status === 409 ? '用户名已被使用' : failure.message || '连接失败，请重试。')
      if (failure.status === 429) setCooldown(failure.retryAfter || 60)
    } finally { locked.current = false; setBusy(false) }
  }
  return <dialog ref={ref} className="auth-dialog" aria-labelledby="auth-title" onCancel={event => { event.preventDefault(); session.closeLogin() }}>
    <button type="button" className="auth-close" aria-label="关闭登录弹窗" onClick={() => session.closeLogin()}><X size={20} /></button>
    <span className="auth-eyebrow">YOUR LITTLE KITCHEN</span><h2 id="auth-title">{mode === 'login' ? '登录智能菜谱助手' : '创建你的厨房账号'}</h2><p className="auth-description">登录后，为你规划菜谱并记住饮食偏好。</p>
    <form onSubmit={submit}>
      <label htmlFor="auth-username">用户名</label><input autoFocus id="auth-username" value={username} onChange={event => setUsername(event.target.value)} autoComplete="username" disabled={busy} aria-describedby="auth-error" maxLength={64} required />
      <label htmlFor="auth-password">密码</label><div className="auth-password"><input id="auth-password" type={visible ? 'text' : 'password'} value={password} onChange={event => setPassword(event.target.value)} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} disabled={busy} aria-describedby="auth-error" minLength={8} maxLength={128} required /><button type="button" aria-label={visible ? '隐藏密码' : '显示密码'} onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={18} /> : <Eye size={18} />}</button></div>
      {mode === 'register' && <><label htmlFor="auth-confirm">确认密码</label><input id="auth-confirm" type={visible ? 'text' : 'password'} value={confirmation} onChange={event => setConfirmation(event.target.value)} autoComplete="new-password" disabled={busy} required /></>}
      <p id="auth-error" className="auth-error" role="alert">{error}{cooldown > 0 ? `（${cooldown} 秒后可重试）` : ''}</p><p className="auth-notice" role="status">{notice}</p>
      <button className="auth-primary" disabled={busy || cooldown > 0}>{busy ? '请稍候…' : mode === 'login' ? '登录' : '注册'}</button>
      <button type="button" className="auth-link" disabled={busy} onClick={switchMode}>{mode === 'login' ? '还没有账号？注册' : '已有账号？返回登录'}</button>
    </form>
  </dialog>
}
