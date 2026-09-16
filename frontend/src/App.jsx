import { BrowserRouter as Router, Routes, Route, useLocation, useNavigate } from 'react-router-dom'
import { useEffect } from 'react'
import CreateMenuPage from './pages/CreateMenuPage'
import MenuProgressPage from './pages/MenuProgressPage'
import AuthProvider from './auth/AuthProvider'
import { useAuth } from './auth/context'
import UserMenu from './auth/UserMenu'

function ProgressGate() {
  const auth = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const data = location.state
  const valid = auth.status === 'authenticated' && data?.ownerUserId === auth.user.id && data?.sessionScope === auth.scope && data?.dishList?.length && data?.runId
  useEffect(() => {
    if (auth.status === 'authenticated' && !valid) navigate('/', { replace: true, state: null })
  }, [auth.status, valid, navigate])
  if (!valid || auth.logoutBusy) return <div className="auth-gate"><p>{auth.status === 'error' ? auth.error : auth.status === 'checking' ? '正在确认登录状态…' : '请登录后从首页重新规划菜谱。'}</p><UserMenu /><button className="auth-secondary" onClick={() => navigate('/', { replace: true, state: null })}>返回首页</button></div>
  return <MenuProgressPage key={`${auth.user.id}:${auth.epoch}`} />
}
function Pages() {
  const auth = useAuth()
  const navigate = useNavigate()
  useEffect(() => {
    if (auth.status === 'anonymous' && !auth.pending) navigate('/', { replace: true, state: null })
  }, [auth.status, auth.pending, navigate])
  return <Routes><Route path="/" element={<CreateMenuPage key={auth.pageVersion} />} /><Route path="/menu-progress" element={<ProgressGate />} /></Routes>
}
export default function App() {
  return <Router><AuthProvider><Pages /></AuthProvider></Router>
}
