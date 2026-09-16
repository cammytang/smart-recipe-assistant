import { useState, useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ArrowLeft, Check, ChefHat, Clock, Copy, Download, ShoppingBasket, X } from 'lucide-react'
import { groupShopping, parseRecipe } from '../utils/recipeView'
import './MenuProgressPage.css'
import { useAuth } from '../auth/context'
import UserMenu from '../auth/UserMenu'

const statusText = { pending: '未开始', in_progress: '进行中', completed: '已完成', failed: '失败', skipped: '已跳过' }

export default function MenuProgressPage() {
  const { session } = useAuth()
  const { state } = useLocation()
  const navigate = useNavigate()
  const { userReq, planningTopic, searchBackend, runId, dishList: confirmedDishList } = state || {}
  const [dishList, setDishList] = useState(() => (confirmedDishList || []).map(dish => ({ ...dish, status: 'pending' })))
  const [activeDishId, setActiveDishId] = useState(confirmedDishList?.[0]?.id)
  const [summaries, setSummaries] = useState({})
  const [sources, setSources] = useState({})
  const [shoppingList, setShoppingList] = useState([])
  const [phase, setPhase] = useState('running')
  const [error, setError] = useState('')
  const [run, setRun] = useState(0)
  const [checked, setChecked] = useState({})
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [copyHint, setCopyHint] = useState('')
  const [failedImages, setFailedImages] = useState({})
  const dialogRef = useRef(null)

  useEffect(() => {
    const topic = planningTopic || userReq
    if (!topic || !confirmedDishList?.length) { navigate('/', { replace: true }); return }
    const controller = new AbortController()
    let completed = false
    const onEvent = event => {
      switch (event.type) {
        case 'todo_list': setDishList(event.tasks); break
        case 'task_status':
          setDishList(previous => previous.map(dish => String(dish.id) === String(event.task_id) ? { ...dish, status: event.status || dish.status, name: event.title || dish.name, intent: event.intent || dish.intent } : dish))
          if (event.summary) setSummaries(previous => ({ ...previous, [event.task_id]: event.summary }))
          if (event.sources_summary) setSources(previous => ({ ...previous, [event.task_id]: event.sources_summary }))
          break
        case 'task_summary_chunk': setSummaries(previous => ({ ...previous, [event.task_id]: `${previous[event.task_id] || ''}${event.content || ''}` })); break
        case 'sources': setSources(previous => ({ ...previous, [event.task_id]: event.latest_sources })); break
        case 'shopping_list': setShoppingList(Array.isArray(event.items) ? event.items : []); break
        case 'error': throw new Error(event.message || event.detail || '菜谱生成失败')
        case 'done': completed = true; setPhase('completed'); break
        default: break
      }
    }
    const receive = async () => {
      let ticket
      try {
        if (controller.signal.aborted) return
        if (run === 0 && !session.claimStream(runId)) throw new Error('此菜谱已启动过生成。如需再次生成，请点击重新生成。')
        ticket = await session.open('/menu/stream', {
          method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
          body: JSON.stringify({ topic, dish_list: confirmedDishList, ...(searchBackend && searchBackend !== 'default' ? { search_api: searchBackend } : {}) }), signal: controller.signal,
        })
        const reader = ticket.response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        const consume = frame => {
          const data = frame.split(/\r?\n/).filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n')
          if (data) onEvent(JSON.parse(data))
        }
        while (!controller.signal.aborted) {
          const { done, value } = await reader.read()
          ticket.check()
          if (controller.signal.aborted) return
          buffer += decoder.decode(value, { stream: !done })
          const frames = buffer.split(/\r?\n\r?\n/)
          buffer = frames.pop() || ''
          frames.forEach(consume)
          if (done) { if (buffer.trim()) consume(buffer); break }
        }
        if (!completed) throw new Error('连接提前中断，请重新生成。')
      } catch (failure) {
        if (!controller.signal.aborted && failure.name !== 'AbortError') { setError(failure.message); setPhase('failed'); controller.abort() }
      } finally { ticket?.release() }
    }
    // StrictMode cleanup cancels the first scheduled setup before it can POST.
    const timer = setTimeout(receive, 0)
    return () => { clearTimeout(timer); controller.abort() }
  }, [userReq, planningTopic, searchBackend, confirmedDishList, navigate, run, runId, session])

  useEffect(() => {
    const dialog = dialogRef.current
    if (drawerOpen && !dialog.open) dialog.showModal()
    if (!drawerOpen && dialog.open) dialog.close()
  }, [drawerOpen])

  const activeDish = dishList.find(dish => String(dish.id) === String(activeDishId))
  const summary = summaries[activeDishId] || ''
  const recipe = parseRecipe(summary)
  const groups = groupShopping(shoppingList)
  const shoppingCount = Object.values(groups).reduce((count, items) => count + items.length, 0)
  const finished = dishList.filter(dish => ['completed', 'failed', 'skipped'].includes(dish.status)).length
  const successful = dishList.filter(dish => dish.status === 'completed').length
  const toggle = key => setChecked(previous => ({ ...previous, [key]: !previous[key] }))
  const stepKey = index => `step:${activeDishId}:${index}`
  const nextStep = recipe.steps.findIndex((_, index) => !checked[stepKey(index)])
  const shoppingText = Object.entries(groups).map(([region, items]) => `${region}\n${items.map(item => `${checked[`buy:${item.name}`] ? '[x]' : '[ ]'} ${item.name} ${item.quantity}`).join('\n')}`).join('\n\n')
  const copy = async () => {
    try { await navigator.clipboard.writeText(shoppingText); setCopyHint('已复制，可以粘贴到备忘录。') }
    catch { setCopyHint('无法访问剪贴板，请下载清单后保存。') }
  }
  const download = () => {
    const url = URL.createObjectURL(new Blob([shoppingText], { type: 'text/plain;charset=utf-8' }))
    const anchor = document.createElement('a')
    anchor.href = url; anchor.download = '购物清单.txt'; anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    setCopyHint('已导出文字清单。')
  }
  const retry = () => {
    setPhase('running'); setError(''); setSummaries({}); setSources({}); setShoppingList([]); setChecked({})
    setDishList(confirmedDishList.map(dish => ({ ...dish, status: 'pending' })))
    setRun(previous => previous + 1)
  }

  return (
    <main className="recipe-panel">
      <header className="recipe-top">
        <div className="recipe-top-inner">
          <div className="recipe-toolbar"><button className="recipe-back" onClick={() => navigate('/')}><ArrowLeft size={17} /><span>调整菜单</span></button><span className="recipe-brand"><ChefHat size={20} />我的厨房</span><button className="recipe-shop-top" onClick={() => setDrawerOpen(true)}><ShoppingBasket size={17} /><span>查看购物清单</span></button><UserMenu /></div>
          <div className="recipe-progress-label"><span>{phase === 'failed' ? '生成中断' : phase === 'completed' ? (successful === dishList.length ? '菜谱准备就绪，开始做饭吧' : '生成结束，部分菜谱未完成') : '正在为你整理菜谱'}</span><span>已处理 {finished}/{dishList.length} · 成功 {successful} 道</span></div>
          <progress className="recipe-progress" value={finished} max={dishList.length || 1} aria-label="菜谱生成进度" />
          <nav className="recipe-tabs" aria-label="选择菜品">{dishList.map((dish, index) => <button key={dish.id} className={`recipe-tab ${String(activeDishId) === String(dish.id) ? 'selected' : ''}`} aria-pressed={String(activeDishId) === String(dish.id)} onClick={() => setActiveDishId(dish.id)}><span className="recipe-tab-number">{index + 1}</span><span><strong>{dish.name}</strong><small className={`recipe-status ${dish.status}`}>{statusText[dish.status] || '未开始'}</small></span></button>)}</nav>
        </div>
      </header>

      <div className="recipe-content">
        {error && <div className="recipe-error" role="alert">{error}<button onClick={retry}>重新生成</button></div>}
        {activeDish && <>
          <section className="recipe-hero">
            <div className="recipe-cover">{recipe.image && !failedImages[activeDishId] ? <img src={recipe.image} alt={activeDish.name} onError={() => setFailedImages(previous => ({ ...previous, [activeDishId]: true }))} /> : <div className="recipe-cover-placeholder"><ChefHat size={60} strokeWidth={1} /><span>为这一餐，留一点期待</span><small>暂无菜品图片</small></div>}</div>
            <div className="recipe-heading"><span className="recipe-eyebrow">TODAY’S MENU · 今日菜单</span><h1>{activeDish.name}</h1><p>{activeDish.intent}</p><span className="recipe-time"><Clock size={16} />{recipe.duration || '耗时待补充'}</span></div>
          </section>

          {activeDish.status !== 'completed' && <p className="recipe-notice" role="status">{activeDish.status === 'failed' ? '这道菜生成失败，可重新生成整套菜单。' : activeDish.status === 'skipped' ? '未找到可用菜谱，请返回调整菜单。' : '正在整理这道菜，内容会自动更新；完成后即可勾选烹饪步骤。'}</p>}
          <section className="recipe-section"><div className="recipe-section-title"><h2>准备食材</h2><span>备好一项，勾选一项</span></div>{recipe.ingredients.length ? <div className="recipe-ingredients">{recipe.ingredients.map((ingredient, index) => <label key={`${activeDishId}-${index}`} className={checked[`ingredient:${activeDishId}:${index}`] ? 'is-checked' : ''}><input type="checkbox" disabled={activeDish.status !== 'completed'} checked={Boolean(checked[`ingredient:${activeDishId}:${index}`])} onChange={() => toggle(`ingredient:${activeDishId}:${index}`)} /><span>{ingredient}</span></label>)}</div> : <p className="recipe-empty">{activeDish.status === 'completed' ? '没有提取到食材清单，请查看下方原文。' : '食材清单等待整理…'}</p>}</section>
          <section className="recipe-section"><div className="recipe-section-title"><h2>一步一步，做好这道菜</h2><span>{recipe.steps.filter((_, index) => checked[stepKey(index)]).length}/{recipe.steps.length} 步完成</span></div><div className="recipe-steps">{recipe.steps.map((step, index) => <article key={`${activeDishId}-${index}`} className={`recipe-step ${checked[stepKey(index)] ? 'done' : nextStep === index ? 'current' : ''}`}><span className="recipe-step-marker">{checked[stepKey(index)] ? <Check size={17} /> : index + 1}</span><div><span className="recipe-step-label">STEP {String(index + 1).padStart(2, '0')}{nextStep === index && activeDish.status === 'completed' ? ' · 当前步骤' : ''}</span><p>{step}</p><button disabled={activeDish.status !== 'completed'} aria-pressed={Boolean(checked[stepKey(index)])} onClick={() => toggle(stepKey(index))}>{checked[stepKey(index)] ? '✓ 已完成 · 撤销' : '标记完成'}</button></div></article>)}</div>{!recipe.steps.length && <p className="recipe-empty">{activeDish.status === 'completed' ? '没有提取到步骤，请查看下方原文。' : '做法正在路上，请稍候…'}</p>}{recipe.steps.length > 0 && nextStep === -1 && <p className="recipe-complete" role="status">这道菜做好了，享用你的劳动成果吧！</p>}</section>
          {recipe.notes.length > 0 && <section className="recipe-tips"><h2>烹饪小贴士与补充信息</h2>{recipe.notes.map((note, index) => <p key={index}>{note}</p>)}</section>}
          {summary && <details className="recipe-original"><summary>查看完整菜谱与参考来源</summary><pre>{summary}</pre>{sources[activeDishId] && <pre>{typeof sources[activeDishId] === 'string' ? sources[activeDishId] : JSON.stringify(sources[activeDishId], null, 2)}</pre>}</details>}
        </>}
      </div>
      <div className="recipe-floating"><button onClick={() => setDrawerOpen(true)}><ShoppingBasket size={20} />查看购物清单 <span>{shoppingCount} 件</span></button></div>

      <dialog ref={dialogRef} className="shopping-drawer" onCancel={() => setDrawerOpen(false)} onClose={() => setDrawerOpen(false)} aria-labelledby="shopping-title">
        <div className="shopping-shell"><header className="shopping-header"><div><p>SHOPPING LIST</p><h2 id="shopping-title">一次买齐，轻松开做</h2><span>{shoppingCount} 项食材 · 已购 {Object.values(groups).flat().filter(item => checked[`buy:${item.name}`]).length} 项</span></div><button autoFocus onClick={() => setDrawerOpen(false)} aria-label="关闭购物清单"><X size={22} /></button></header>
          <div className="shopping-body">{!shoppingCount && <p className="recipe-empty">{phase === 'running' ? '菜谱生成后，食材会自动汇总到这里。' : '暂无购物清单，请参考各道菜的食材明细。'}</p>}{Object.entries(groups).map(([region, items]) => <section className="shopping-region" key={region}><h3>{region}<span>{items.length} 项</span></h3>{items.map(item => <label key={item.name} className={checked[`buy:${item.name}`] ? 'is-checked' : ''}><input type="checkbox" checked={Boolean(checked[`buy:${item.name}`])} onChange={() => toggle(`buy:${item.name}`)} /><span><strong>{item.name}</strong>{item.sources.length > 0 && <small>用于：{item.sources.join('、')}</small>}</span><b>{item.quantity}</b></label>)}</section>)}</div>
          <footer className="shopping-footer"><p role="status">{copyHint || '同类食材已合并；不同单位分别保留，请按实际人数核对用量。'}</p><div><button onClick={copy} disabled={!shoppingCount}><Copy size={17} />一键复制清单</button><button onClick={download} disabled={!shoppingCount}><Download size={17} />导出清单</button></div></footer>
        </div>
      </dialog>
    </main>
  )
}
