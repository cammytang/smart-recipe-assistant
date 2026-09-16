import { useEffect, useRef, useState } from 'react'
import { X, LogOut } from 'lucide-react'
import { useAuth } from './context'
const fields = [['diet_preferences', '饮食偏好'], ['allergies', '过敏 / 忌口'], ['disliked_ingredients', '不喜欢的食材'], ['favorite_ingredients', '常用食材'], ['recent_dishes', '最近确认的菜品'], ['rejected_patterns', '其他偏好']]
export default function ProfileDrawer() {
  const auth = useAuth()
  return auth.drawer && auth.user ? <Drawer key={auth.user.id} auth={auth} /> : null
}
function Drawer({ auth }) {
  const { session, user, profile, profileStatus, error, logoutBusy } = auth
  const ref = useRef(null)
  const [confirm, setConfirm] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [localError, setLocalError] = useState('')
  const lock = useRef(false)
  useEffect(() => {
    const previous = document.activeElement
    const modal = ref.current
    modal.showModal()
    return () => { modal.close(); if (previous?.isConnected) previous.focus() }
  }, [])
  const clear = async () => {
    if (lock.current) return
    lock.current = true; setClearing(true); setLocalError('')
    try { await session.clearProfile(); setConfirm(false) }
    catch (failure) { if (failure.name !== 'AbortError') setLocalError(failure.message) }
    finally { lock.current = false; setClearing(false) }
  }
  return <dialog ref={ref} className="auth-drawer" aria-labelledby="profile-title" onCancel={event => { event.preventDefault(); session.patch({ drawer: false }) }}>
    <header><div><span className="auth-eyebrow">MY PROFILE</span><h2 id="profile-title">{user.username} 的饮食画像</h2></div><button className="auth-close" aria-label="关闭用户画像" onClick={() => session.patch({ drawer: false })}><X size={20} /></button></header>
    <div className="auth-profile-body">
      {profileStatus === 'loading' && <p role="status">正在读取你的偏好…</p>}
      {profileStatus === 'error' && <button className="auth-secondary" onClick={() => session.loadProfile()}>重新加载画像</button>}
      {profile && <>{fields.map(([field, title]) => <section key={field}><h3>{title}</h3><div className="auth-tags">{profile[field]?.length ? profile[field].map((item, index) => <span key={index}>{item}</span>) : <p>暂无记录</p>}</div></section>)}<section><h3>常见用餐人数</h3><p>{profile.common_serving_size || '暂无记录'}</p></section><p className="auth-description">最后更新：{profile.updated_at ? new Date(profile.updated_at).toLocaleString() : '暂无记录'}</p></>}
      <p className="auth-error" role="alert">{localError || error}</p>
      {confirm ? <div className="auth-clear-confirm"><p>清空全部长期偏好？此操作不会删除账号。</p><small>之后确认菜单可能重新记录偏好。</small><div><button className="auth-secondary" disabled={clearing || logoutBusy} onClick={clear}>{clearing ? '清空中…' : '确认清空'}</button><button className="auth-link" disabled={clearing} onClick={() => setConfirm(false)}>取消</button></div></div> : <button className="auth-secondary" disabled={!profile || logoutBusy} onClick={() => setConfirm(true)}>清空长期记忆</button>}
    </div><footer><button className="auth-primary" disabled={logoutBusy || clearing} onClick={() => session.logout()}><LogOut size={17} />{logoutBusy ? '正在退出…' : '退出登录'}</button></footer>
  </dialog>
}
