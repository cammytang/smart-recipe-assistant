import { useEffect, useEffectEvent, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowUp, Check, ChefHat, Pencil, Plus, User } from 'lucide-react'
import './CreateMenuPage.css'
import { useAuth } from '../auth/context'
import UserMenu from '../auth/UserMenu'

const welcome = { id: 'welcome', role: 'assistant', text: '今天想吃什么？告诉我想用的食材、几个人吃，以及你的饮食偏好。我会先为你搭配一份菜单，确认后再整理详细做法和购物清单。' }
const examples = ['我想吃土豆，但最近在减脂，两个人吃。', '冰箱有番茄和鸡蛋，想做一顿快手晚餐。', '两个人吃，不吃辣，想要两菜一汤。']
const message = (role, text, extra = {}) => ({ id: crypto.randomUUID(), role, text, ...extra })

export default function CreateMenuPage() {
  const navigate = useNavigate()
  const { session, status: authStatus, user, scope, logoutBusy, error: authError } = useAuth()
  const [messages, setMessages] = useState([welcome])
  const [input, setInput] = useState('')
  const [topic, setTopic] = useState('')
  const [plan, setPlan] = useState(null)
  const [status, setStatus] = useState('idle')
  const [retryTopic, setRetryTopic] = useState(null)
  const inputRef = useRef(null)
  const endRef = useRef(null)
  const requestRef = useRef(null)
  const busyRef = useRef(false)
  const busy = status === 'planning' || status === 'confirming'

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, status])

  useEffect(() => () => {
    requestRef.current?.abort()
  }, [])

  const append = (entry) => setMessages(previous => [...previous, entry])

  const fetchPlan = async (nextTopic) => {
    if (!session.require({ kind: 'plan', payload: { topic: nextTopic, text: nextTopic }, ownerUserId: user?.id })) return
    if (busyRef.current) return
    busyRef.current = true
    setStatus('planning')
    setPlan(null)
    setRetryTopic(null)
    const controller = new AbortController()
    requestRef.current = controller
    try {
      const payload = await session.request('/menu/plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic: nextTopic }),
        signal: controller.signal,
      }, { kind: 'plan', payload: { topic: nextTopic, text: nextTopic } })
      if (!Array.isArray(payload.dish_list) || !payload.dish_list.length || payload.dish_list.some(dish => !dish || typeof dish.name !== 'string' || !dish.name.trim())) {
        throw new Error('暂时没有获得有效的菜单方案')
      }
      const entry = message('assistant', '我为你搭配了这份菜单，看看是否合你的心意？', { dishes: payload.dish_list })
      setPlan({ id: entry.id, dishes: payload.dish_list, topic: nextTopic })
      append(entry)
    } catch (error) {
      if (error.name !== 'AbortError') {
        append(message('assistant', `${error.message}。可以重试，或继续告诉我你的需求。`, { error: true }))
        setRetryTopic(nextTopic)
      }
    } finally {
      if (!controller.signal.aborted) {
        busyRef.current = false
        setStatus('idle')
      }
    }
  }

  const send = (text = input) => {
    const value = text.trim()
    if (!value || busyRef.current) return
    const nextTopic = topic
      ? `${topic}\n${plan ? `上次建议的菜品：${plan.dishes.map(dish => dish.name).join('、')}\n` : ''}用户最新补充或修改（与之前冲突时以本次为准）：${value}`
      : value
    if (!session.require({ kind: 'plan', payload: { topic: nextTopic, text: value }, ownerUserId: user?.id })) { setInput(value); return }
    append(message('user', value))
    setInput('')
    setTopic(nextTopic)
    fetchPlan(nextTopic)
  }

  const revise = () => {
    if (busyRef.current || !plan || status === 'editing') return
    append(message('user', '我想修改方案'))
    append(message('assistant', `想调整哪道菜？你可以告诉我换掉${plan.dishes[0].name}，或调整口味、份量和搭配。`))
    setStatus('editing')
    inputRef.current?.focus()
  }

  const confirm = async (selectedPlan = plan) => {
    if (!selectedPlan || busyRef.current || status === 'editing' || input.trim()) return
    if (!session.require({ kind: 'confirm', payload: selectedPlan, ownerUserId: user?.id })) return
    busyRef.current = true
    setStatus('confirming')
    append(message('user', '同意生成，就按这份方案来'))
    append(message('assistant', '好的，正在为您生成详细菜谱和购物清单…'))
    const controller = new AbortController()
    requestRef.current = controller
    try {
      const result = await session.request('/memory/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_requirement: selectedPlan.topic, dish_list: selectedPlan.dishes }),
        signal: controller.signal,
      }, { kind: 'confirm', payload: selectedPlan })
      session.updateProfile(result.memory)
      navigate('/menu-progress', { state: { ownerUserId: user.id, sessionScope: scope, runId: crypto.randomUUID(), userReq: selectedPlan.topic, planningTopic: selectedPlan.topic, searchBackend: 'default', dishList: selectedPlan.dishes } })
    } catch (error) {
      if (error.name !== 'AbortError') {
        append(message('assistant', `${error.message}，方案已保留，请点击「同意生成」重试。`, { error: true }))
        setStatus('idle')
        busyRef.current = false
      }
    }
  }

  const resumePending = useEffectEvent(() => {
    const intent = session.takeIntent()
    if (!intent) return
    if (intent.kind === 'plan') {
      setInput('')
      setTopic(intent.payload.topic)
      append(message('user', intent.payload.text))
      fetchPlan(intent.payload.topic)
    } else if (intent.kind === 'confirm') {
      setPlan(intent.payload)
      confirm(intent.payload)
    }
  })
  useEffect(() => {
    if (authStatus !== 'authenticated') return
    const timer = setTimeout(() => resumePending(), 0)
    return () => clearTimeout(timer)
  }, [authStatus])

  const reset = () => {
    if (busyRef.current) return
    session.cancelIntent()
    setMessages([welcome])
    setTopic('')
    setPlan(null)
    setInput('')
    setRetryTopic(null)
    setStatus('idle')
    inputRef.current?.focus()
  }

  if (authStatus === 'error' || logoutBusy) return <div className="auth-gate"><p>{logoutBusy ? '正在退出…' : authError || '暂时无法确认登录状态，请重试。'}</p><UserMenu /></div>

  return (
    <main className="menu-chat">
      <header className="chat-header">
        <div className="chat-brand"><span className="chat-logo"><ChefHat size={25} /></span><div><h1>智能菜谱助手</h1><p>聊聊想吃什么，一起安排好这一餐</p></div></div>
        <div className="auth-header-actions"><button className="chat-new" onClick={reset} disabled={busy}><Plus size={17} /><span>新建对话</span></button><UserMenu /></div>
      </header>

      <section className="chat-scroll" aria-label="菜单规划对话">
        <div className="chat-thread" role="log" aria-live="polite" aria-relevant="additions text">
          <div className="chat-intro"><span>从一句「今天想吃什么」开始</span><p>说出需求 → 调整方案 → 生成菜谱</p></div>
          {messages.map(entry => {
            const current = entry.id === plan?.id
            return (
              <article key={entry.id} className={`chat-message ${entry.role}`}>
                <span className="chat-avatar" aria-label={entry.role === 'assistant' ? '菜谱助手' : '你'}>{entry.role === 'assistant' ? <ChefHat size={20} /> : <User size={20} />}</span>
                <div className="chat-message-body">
                  <div className={`chat-bubble ${entry.error ? 'chat-error' : ''}`}>{entry.text}</div>
                  {entry.dishes && <div className="chat-plan">
                    <div className="chat-plan-heading"><h2>建议方案</h2><span>{current ? '等待你的确认' : '历史方案'}</span></div>
                    <div className="chat-dishes">{entry.dishes.map((dish, index) => <div className="chat-dish" key={`${dish.id}-${index}`}><span className="chat-dish-number">{String(index + 1).padStart(2, '0')}</span><div><h3>{dish.name}</h3>{dish.intent && <p>{dish.intent}</p>}</div></div>)}</div>
                    <p className="chat-plan-note">确认后，为你整理详细做法和购物清单。</p>
                    <div className="chat-plan-actions"><button className="chat-primary" onClick={() => confirm()} disabled={!current || busy || status === 'editing' || Boolean(input.trim())}><Check size={16} />{current && status === 'confirming' ? '正在生成…' : '同意生成'}</button><button className="chat-secondary" onClick={revise} disabled={!current || busy || status === 'editing'}><Pencil size={15} />修改方案</button></div>
                    {current && (status === 'editing' || input.trim()) && <p className="chat-plan-note">请先发送修改意见，确认更新后的方案。</p>}
                  </div>}
                </div>
              </article>
            )
          })}
          {messages.length === 1 && <div className="chat-examples"><p>试着这样说</p>{examples.map(example => <button key={example} onClick={() => send(example)} disabled={busy}>{example}<span aria-hidden="true">↗</span></button>)}</div>}
          {status === 'planning' && <div className="chat-working" role="status"><span className="chat-dot" />正在根据你的需求搭配菜单…</div>}
          {retryTopic && !busy && <button className="chat-retry chat-secondary" onClick={() => fetchPlan(retryTopic)}>重新规划</button>}
          <div ref={endRef} />
        </div>
      </section>

      <footer className="chat-footer">
        <form className="chat-composer" onSubmit={event => { event.preventDefault(); send() }}>
          <label className="chat-sr-only" htmlFor="menu-message">告诉我用餐需求或修改意见</label>
          <textarea id="menu-message" ref={inputRef} value={input} onChange={event => setInput(event.target.value)} disabled={busy || logoutBusy || authStatus === 'error'} rows={2} placeholder={status === 'editing' ? '想换哪道菜？告诉我你的修改意见…' : '输入食材、人数或饮食偏好…'} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) { event.preventDefault(); send() } }} />
          <div className="chat-composer-tools"><button type="submit" className="chat-send" disabled={busy || !input.trim()} aria-label="发送消息"><ArrowUp size={21} /></button></div>
        </form>
        <p className="chat-input-hint" role="status">Enter 发送 · Shift + Enter 换行 · 确认方案后再生成菜谱</p>
      </footer>
    </main>
  )
}
