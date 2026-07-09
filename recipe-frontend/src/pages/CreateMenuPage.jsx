import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

export default function CreateMenuPage() {
  const navigate = useNavigate()
  const [userReq, setUserReq] = useState('低脂不辣，现有食材 番茄 土豆')
  const [searchBackend, setSearchBackend] = useState('default')
  const [dishList, setDishList] = useState([])
  const [planningTopic, setPlanningTopic] = useState('')
  const [revisionText, setRevisionText] = useState('')
  const [isPlanning, setIsPlanning] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')

  const buildPayload = (topic) => {
    const payload = { topic }
    if (searchBackend !== 'default') {
      payload.search_api = searchBackend
    }
    return payload
  }

  const fetchPlan = async (topic) => {
    setIsPlanning(true)
    setErrorMessage('')
    setPlanningTopic(topic)

    try {
      const res = await fetch('http://127.0.0.1:8000/menu/plan', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(buildPayload(topic))
      })

      if (!res.ok) throw new Error(`HTTP错误: ${res.status}`)
      const payload = await res.json()
      setDishList(Array.isArray(payload.dish_list) ? payload.dish_list : [])
    } catch (err) {
      console.error('菜单规划失败', err)
      setDishList([])
      setErrorMessage(err.message || '菜单规划失败，请稍后重试')
    } finally {
      setIsPlanning(false)
    }
  }

  const handlePlan = () => {
    const topic = userReq.trim()
    if (!topic) return alert('请填写用餐需求')
    fetchPlan(topic)
  }

  const handleReplan = () => {
    const feedback = revisionText.trim()
    if (!feedback) return alert('请填写希望调整的地方')

    const revisedTopic = `${userReq.trim()}\n用户对上次菜单的修改意见：${feedback}`
    setRevisionText('')
    fetchPlan(revisedTopic)
  }

  const handleConfirm = () => {
    if (!dishList.length) return alert('请先生成可确认的菜单规划')

    navigate('/menu-progress', {
      state: {
        userReq: userReq.trim(),
        planningTopic: planningTopic || userReq.trim(),
        searchBackend,
        dishList
      }
    })
  }

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center px-4 py-10">
      <div className="w-full max-w-2xl bg-white rounded-2xl shadow-lg p-8">
        <div className="flex items-center gap-4 mb-8">
          <div className="w-14 h-14 rounded-xl bg-indigo-600 flex items-center justify-center text-white text-2xl">
            🥘
          </div>
          <div>
            <h1 className="text-3xl font-bold text-gray-800">智能菜谱助手</h1>
            <p className="text-gray-500 mt-1">自动解析用餐需求，生成整套菜单、购物清单与详细做法</p>
          </div>
        </div>

        <div className="mb-6">
          <label className="block text-lg font-medium text-gray-700 mb-2">用餐需求</label>
          <textarea
            value={userReq}
            onChange={(e) => setUserReq(e.target.value)}
            rows={5}
            className="w-full border border-gray-200 rounded-xl p-4 text-base focus:outline-indigo-500 focus:border-indigo-400 resize-none"
            placeholder="例：两人减脂晚餐，冰箱有鸡蛋、西兰花，不吃辣，30分钟快手菜"
          />
        </div>

        <div className="mb-8">
          <label className="block text-lg font-medium text-gray-700 mb-2">搜索引擎</label>
          <select
            value={searchBackend}
            onChange={(e) => setSearchBackend(e.target.value)}
            className="w-full border border-gray-200 rounded-xl p-4 text-base bg-white focus:outline-indigo-500"
          >
            <option value="default">沿用后端配置</option>
            <option value="tavily">Tavily</option>
            <option value="duckduckgo">DuckDuckGo</option>
          </select>
        </div>

        <button
          onClick={handlePlan}
          disabled={isPlanning}
          className="w-full py-4 bg-indigo-600 text-white rounded-xl text-lg font-medium hover:bg-indigo-700 active:bg-indigo-800 disabled:cursor-not-allowed disabled:bg-indigo-300 transition-colors"
        >
          {isPlanning ? '正在规划菜单...' : '先规划菜单'}
        </button>

        {errorMessage && (
          <div className="mt-5 rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">
            {errorMessage}
          </div>
        )}

        {dishList.length > 0 && (
          <div className="mt-8 rounded-xl border border-indigo-100 bg-indigo-50/40 p-5">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <h2 className="text-xl font-semibold text-gray-800">请确认菜单规划</h2>
                <p className="mt-1 text-sm text-gray-500">
                  同意后再进入生成页，继续整理做法、购物清单和完整菜单。
                </p>
              </div>
              <button
                onClick={handleConfirm}
                className="shrink-0 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
              >
                同意，开始生成
              </button>
            </div>

            <div className="space-y-3">
              {dishList.map((dish) => (
                <div key={dish.id} className="rounded-lg border border-gray-200 bg-white p-4">
                  <div className="flex items-start justify-between gap-3">
                    <h3 className="font-medium text-gray-800">{dish.name}</h3>
                    <span className="rounded-full bg-slate-100 px-2 py-1 text-xs text-slate-600">
                      菜品 {dish.id}
                    </span>
                  </div>
                  <p className="mt-2 text-sm leading-6 text-gray-600">{dish.intent}</p>
                  <p className="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-xs leading-5 text-gray-500">
                    查询：{dish.query}
                  </p>
                </div>
              ))}
            </div>

            <div className="mt-5">
              <label className="mb-2 block text-sm font-medium text-gray-700">不满意的话，写下调整要求</label>
              <div className="flex gap-3">
                <textarea
                  value={revisionText}
                  onChange={(e) => setRevisionText(e.target.value)}
                  rows={2}
                  className="min-h-20 flex-1 resize-none rounded-lg border border-gray-200 bg-white p-3 text-sm focus:border-indigo-400 focus:outline-indigo-500"
                  placeholder="例：不要汤，换成两道快手热菜；少油，尽量只用番茄和土豆"
                />
                <button
                  onClick={handleReplan}
                  disabled={isPlanning}
                  className="h-10 rounded-lg border border-gray-200 bg-white px-4 text-sm font-medium hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-gray-400"
                >
                  重新规划
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
