const clean = text => text.replace(/\*\*|__/g, '').replace(/^\s*#{1,6}\s*/, '').trim()

export function parseRecipe(markdown = '') {
  const result = { ingredients: [], steps: [], notes: [], duration: '', image: '' }
  const image = markdown.match(/!\[[^\]]*\]\((https?:\/\/[^\s)]+)\)/)
  if (image) result.image = image[1]
  let section = ''
  for (const raw of markdown.replace(/!\[[^\]]*\]\([^)]*\)/g, '').split('\n')) {
    let line = clean(raw)
    if (!line || /^[-|: ]+$/.test(line) || line === '菜品详细整理结果') continue
    const heading = line.match(/^(?:[一二三四五六七八九十\d]+[、.．）)]\s*)?(食材清单|食材明细|用料|烹饪步骤|制作步骤|做法|总耗时|烹饪总耗时|预估热量|难度|烹饪小贴士|小贴士)[：:]?\s*(.*)$/)
    if (heading) {
      const name = heading[1]
      section = /食材|用料/.test(name) ? 'ingredients' : /步骤|做法/.test(name) ? 'steps' : /耗时/.test(name) ? 'duration' : 'notes'
      line = heading[2]
      if (!line) continue
    } else if (/^#{1,6}\s/.test(raw) && !/^\s*(?:Step\s*\d+|步骤\s*\d+)/i.test(line)) {
      section = 'notes'
    }
    line = line.replace(/^[-*+]\s+/, '').replace(/^\[[ xX]\]\s*/, '')
    if (section === 'ingredients') {
      if (line.includes('|')) {
        const cells = line.split('|').map(item => item.trim()).filter(Boolean)
        if (/^(食材|名称|原料)$/.test(cells[0])) continue
        line = cells.join(' ')
      }
      result.ingredients.push(line)
    } else if (section === 'steps') {
      const numbered = /^(?:\d+[.、．）)]|Step\s*\d+[:：.\s]*|步骤\s*[\d一二三四五六七八九十]+[:：.、\s]*)/i
      if (numbered.test(line) || !result.steps.length || /^\s*[-*+]\s/.test(raw)) result.steps.push(line.replace(numbered, '').trim())
      else result.steps[result.steps.length - 1] += `\n${line}`
    } else if (section === 'duration') {
      result.duration += `${result.duration ? ' ' : ''}${line}`
    } else if (section === 'notes') result.notes.push(line)
  }
  return result
}

const regions = [
  ['肉禽区', /肉|鸡胸|鸡腿|鸡翅|排骨|牛腩|培根|香肠/],
  ['水产区', /鱼|虾|蟹|贝|蛤|鱿/],
  ['蛋奶豆制品区', /蛋|奶|豆腐|豆干|芝士|黄油/],
  ['调料区', /盐|油|酱|醋|糖|胡椒|花椒|料酒|淀粉|孜然|八角|桂皮|味精|鸡精/],
  ['蔬菜区', /菜|土豆|番茄|西红柿|萝卜|瓜|葱|姜|蒜|椒|菇|木耳|莲藕|茄子|豆角|豌豆|玉米/],
  ['主食区', /米|面|粉|馒头|面包/],
]

export function groupShopping(items = []) {
  const merged = new Map()
  for (const raw of items) {
    if (typeof raw !== 'string' || !raw.trim()) continue
    const sources = raw.match(/（用于：(.+)）$/)?.[1]?.split('、') || []
    const text = clean(raw.replace(/（用于：.+）$/, '')).replace(/^[-*+]\s*/, '')
    const match = /\d\s*[-~～至到/]\s*\d/.test(text) ? null : text.match(/^([^\d]+?)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(千克|公斤|kg|克|g|毫升|ml|升|个|根|颗|只|片|勺|把|袋|盒|块)\s*$/i)
    const vague = text.match(/^(.+?)\s*[:：]?\s*(适量|少许|若干)$/)
    const name = (match?.[1] || vague?.[1] || text).trim().replace(/[：:]$/, '')
    if (!merged.has(name)) merged.set(name, { name, quantities: new Map(), notes: new Set(), sources: new Set() })
    const item = merged.get(name)
    sources.forEach(source => item.sources.add(source))
    if (match) {
      let amount = Number(match[2]) * Math.max(1, sources.length)
      let unit = match[3].toLowerCase()
      if (['千克', '公斤', 'kg'].includes(unit)) { amount *= 1000; unit = '克' }
      if (unit === 'g') unit = '克'
      if (unit === '升') { amount *= 1000; unit = '毫升' }
      if (unit === 'ml') unit = '毫升'
      item.quantities.set(unit, (item.quantities.get(unit) || 0) + amount)
    } else if (vague) item.notes.add(vague[2])
    else item.notes.add('用量见菜谱')
  }
  const groups = {}
  for (const item of merged.values()) {
    const region = regions.find(([, pattern]) => pattern.test(item.name))?.[0] || '其他食材'
    const quantity = [...item.quantities].map(([unit, amount]) => `${Number(amount.toFixed(3))}${unit}`).concat([...item.notes]).join(' + ')
    ;(groups[region] ||= []).push({ name: item.name, quantity, sources: [...item.sources] })
  }
  return groups
}
