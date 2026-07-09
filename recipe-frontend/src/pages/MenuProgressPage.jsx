import { useState, useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

export default function MenuProgressPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const { userReq, planningTopic, searchBackend, dishList: confirmedDishList } = location.state || {}

  // 全局状态
  const [dishList, setDishList] = useState([])
  const [activeDishId, setActiveDishId] = useState(null)
  const [sourcesByTaskId, setSourcesByTaskId] = useState({})
  const [currentSources, setCurrentSources] = useState('暂无可用来源')
  const [summaryByTaskId, setSummaryByTaskId] = useState({})
  const [summaryContent, setSummaryContent] = useState('暂无可用信息')
  const [finishedCount, setFinishedCount] = useState(0)
  const [finalMenu, setFinalMenu] = useState(null)
  const [shoppingList, setShoppingList] = useState([])
  const [phase, setPhase] = useState('running')
  const [errorMessage, setErrorMessage] = useState('')
  const eventSourceRef = useRef(null)

  useEffect(()=>{
    console.log('dishList: ', dishList)
  },[dishList])

  const resetRunState = () => {
    setActiveDishId(null)
    setSourcesByTaskId({})
    setCurrentSources('暂无可用来源')
    setSummaryByTaskId({})
    setSummaryContent('暂无可用信息')
    setFinishedCount(0)
    setFinalMenu(null)
    setShoppingList([])
    setErrorMessage('')
  }

  const buildStreamPayload = (topic, tasks) => {
    const payload = {
      topic,
      dish_list: tasks
    }
    if (searchBackend && searchBackend !== 'default') {
      payload.search_api = searchBackend
    }
    return payload
  }

  const startStream = async (tasks, topic) => {
    eventSourceRef.current?.abort()
    const abortController = new AbortController()
    eventSourceRef.current = abortController

    resetRunState()
    setDishList(tasks.map(item => ({ ...item, status: 'pending' })))
    setActiveDishId(tasks[0]?.id || null)
    setPhase('running')

    try {
      const res = await fetch('http://127.0.0.1:8000/menu/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream'
        },
        body: JSON.stringify(buildStreamPayload(topic, tasks)),
        signal: abortController.signal
      })

      if (!res.ok) throw new Error(`HTTP错误: ${res.status}`)
      const reader = res.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          const jsonStr = line.replace(/^data:\s*/, '').trim()
          if (!jsonStr) continue
          try {
            const payload = JSON.parse(jsonStr)
            handleStreamEvent(payload)
          } catch (err) {
            console.error('SSE解析异常', err)
          }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        console.log('SSE连接断开', err)
        setErrorMessage(err.message || '生成过程连接中断')
        setPhase('run_failed')
      }
    }
  }

  useEffect(() => {
    const tasks = Array.isArray(confirmedDishList) ? confirmedDishList : []
    const topic = planningTopic || userReq

    if (!userReq || !topic || tasks.length === 0) {
      navigate('/')
      return
    }

    startStream(tasks, topic)

    return () => {
      eventSourceRef.current?.abort()
    }
  }, [userReq, planningTopic, confirmedDishList, navigate])

  // 事件分发处理
  const handleStreamEvent = (evt) => {
    console.log('SSE事件', evt);
    switch (evt.type) {
      case 'todo_list':
        console.log('接收到菜品任务列表', evt.tasks)
        setDishList(evt.tasks)
        break

      case 'task_status':
        setDishList(prev => prev.map(item =>
          item.id === evt.task_id
            ? {
                ...item,
                ...(evt.status ? { status: evt.status } : {}),
                ...(evt.title ? { name: evt.title } : {}),
                ...(evt.intent ? { intent: evt.intent } : {})
              }
            : item
        ))
        setActiveDishId(evt.task_id)
        if (evt.status === 'completed') setFinishedCount(p => p + 1)
        // 切换菜品清空右侧内容
        setCurrentSources('暂无可用来源')
        setSummaryContent('暂无可用信息')
        break

      case 'sources':
        setSourcesByTaskId(prev => ({
          ...prev,
          [evt.task_id]: evt.latest_sources
        }))
        if (evt.task_id === activeDishId) {
          setCurrentSources(evt.latest_sources)
        }
        break

      case 'task_summary_chunk':
        setSummaryByTaskId(prev => ({
          ...prev,
          [evt.task_id]: `${prev[evt.task_id] || ''}${evt.content}`
        }))
        if (evt.task_id === activeDishId) {
          setSummaryContent(prev => prev + evt.content)
        }
        break

      case 'final_report':
        setFinalMenu(evt.report)
        break

      case 'shopping_list':
        setShoppingList(Array.isArray(evt.items) ? evt.items : [])
        break

      case 'done':
        setPhase('completed')
        break

      default:
        break
    }
  }

  const activeDish = dishList.find(item => item.id === activeDishId)
  const activeSources = activeDishId
    ? (sourcesByTaskId[activeDishId] || currentSources)
    : currentSources
  const activeSummary = activeDishId
    ? (summaryByTaskId[activeDishId] || summaryContent)
    : summaryContent

  // 状态标签样式
  const getStatusClass = (status) => {
    if (status === 'in_progress') return 'bg-amber-100 text-amber-700'
    if (status === 'completed') return 'bg-green-100 text-green-700'
    return 'bg-gray-100 text-gray-600'
  }
  const getStatusText = (status) => {
    if (status === 'in_progress') return '进行中'
    if (status === 'completed') return '已完成'
    if (status === 'skipped') return '已跳过'
    if (status === 'failed') return '失败'
    return '待开始'
  }

  const progressLabel = {
    running: '生成进行中',
    run_failed: '生成中断',
    completed: '生成完成'
  }[phase] || '生成进行中'

  return (
    <div className="min-h-screen bg-slate-50 flex">
      {/* 左侧栏 */}
      <div className="w-72 bg-white border-r border-gray-100 p-5 flex flex-col justify-between">
        <div>
          <button
            onClick={() => navigate('/')}
            className="mb-4 px-3 py-1 border border-gray-200 rounded-lg text-sm hover:bg-slate-50"
          >
            ← 返回
          </button>
          <h2 className="text-xl font-bold mb-4">智能菜谱助手</h2>

          <div className="bg-slate-100 p-3 rounded-xl mb-6">
            <p className="text-sm font-medium text-gray-700">用餐需求</p>
            <p className="text-sm mt-1 text-indigo-700 break-all">{userReq}</p>
          </div>

          <div className="mb-6">
            <p className="text-sm font-medium mb-2">生成进度 {finishedCount}/{dishList.length}</p>
            <div className="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
              <div
                className="h-full bg-indigo-600 transition-all duration-300"
                style={{ width: dishList.length ? `${(finishedCount / dishList.length) * 100}%` : '0%' }}
              />
            </div>
          </div>
        </div>

        <button
          onClick={() => navigate('/')}
          className="w-full py-3 bg-indigo-600 text-white rounded-xl font-medium hover:bg-indigo-700"
        >
          + 开始新菜谱
        </button>
      </div>

      {/* 中间：菜品任务列表 */}
      <div className="flex-1 p-6 overflow-auto">
        <div className="flex items-center justify-between mb-5">
          <span className="px-3 py-1 rounded-full bg-indigo-100 text-indigo-700 text-sm">
            {progressLabel} | 任务进度：{finishedCount}/{dishList.length}
          </span>
          <button className="px-3 py-1 border rounded-lg text-sm">收起流程</button>
        </div>

        {errorMessage && (
          <div className="mb-4 rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">
            {errorMessage}
          </div>
        )}

        <h3 className="text-lg font-semibold mb-4">菜品任务清单</h3>
        <div className="space-y-3">
          {dishList.map(dish => (
            <div
              key={dish.id}
              onClick={() => {
                setActiveDishId(dish.id)
                setCurrentSources(sourcesByTaskId[dish.id] || '暂无可用来源')
                setSummaryContent(summaryByTaskId[dish.id] || '暂无可用信息')
                console.log('切换到菜品', dish)
              }}
              className={`p-4 rounded-xl border cursor-pointer transition-colors
                ${activeDishId === dish.id ? 'border-indigo-500 bg-indigo-50' : 'border-gray-200 bg-white hover:bg-slate-50'}`}
            >
              <div className="flex justify-between items-start">
                <h4 className="font-medium">{dish.name}</h4>
                <span className={`text-xs px-2 py-1 rounded-full ${getStatusClass(dish.status)}`}>
                  {getStatusText(dish.status)}
                </span>
              </div>
              <p className="text-sm text-gray-500 mt-1">{dish.intent}</p>
            </div>
          ))}
          {dishList.length === 0 && (
            <div className="text-center text-gray-400 py-12">等待解析需求生成菜品...</div>
          )}
        </div>

        <div className="mt-6 p-5 bg-white rounded-xl border border-gray-200">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-lg font-semibold">购物清单</h3>
            <span className="text-xs px-2 py-1 rounded-full bg-slate-100 text-slate-600">
              {shoppingList.length} 项
            </span>
          </div>

          {shoppingList.length > 0 ? (
            <ul className="space-y-2">
              {shoppingList.map((item, index) => (
                <li
                  key={`${item}-${index}`}
                  className="flex items-start gap-3 rounded-lg border border-gray-100 bg-slate-50 px-3 py-2 text-sm text-gray-700"
                >
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-indigo-100 text-xs font-semibold text-indigo-700">
                    {index + 1}
                  </span>
                  <span className="leading-6">{item}</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="rounded-lg border border-dashed border-gray-200 bg-slate-50 px-4 py-6 text-center text-sm text-gray-400">
              菜品生成完成后会自动汇总需要购买的食材
            </div>
          )}
        </div>

        {finalMenu && (
          <div className="mt-8 p-5 bg-white rounded-xl border">
            <h3 className="text-lg font-bold mb-3">✅ 整套菜谱生成完成</h3>
            <pre className="text-sm whitespace-pre-wrap text-gray-700 max-h-100 overflow-auto">{finalMenu}</pre>
          </div>
        )}
      </div>

      {/* 右侧：菜品详情面板 */}
      <div className="w-[42%] border-l border-gray-100 bg-white p-6 overflow-auto">
        {activeDish ? (
          <>
            <h3 className="text-xl font-bold">{activeDish.name}</h3>
            <p className="text-gray-600 mt-1 mb-4">{activeDish.intent}</p>
            <div className="text-sm bg-slate-100 px-3 py-2 rounded-lg inline-block mb-6">
              查询：{activeDish.query}
            </div>

            <div className="mb-6">
              <h4 className="font-medium mb-2">最新参考来源</h4>
              <div className="border rounded-xl p-4 min-h-24 text-sm text-gray-600">
                {activeSources}
              </div>
            </div>

            <div>
              <h4 className="font-medium mb-2">菜品整理总结</h4>
              <div className="border rounded-xl p-4 min-h-36 whitespace-pre-wrap text-sm text-gray-700">
                {activeSummary}
              </div>
            </div>
          </>
        ) : (
          <div className="h-full flex items-center justify-center text-gray-400">
            选择左侧菜品查看详情
          </div>
        )}
      </div>
    </div>
  )
}
