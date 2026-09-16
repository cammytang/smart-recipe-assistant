import { test, expect } from '@playwright/test'

async function backend(page) {
  const state = { user: null, plans: 0, streams: 0, failMe: false, failLogout: false, clears: 0, memory: { diet_preferences: ['少油'], allergies: ['虾'], recent_dishes: [], common_serving_size: 2 } }
  await page.route('http://localhost:8000/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    const headers = { 'Access-Control-Allow-Origin': 'http://localhost:5187', 'Access-Control-Allow-Credentials': 'true', 'Access-Control-Allow-Headers': 'content-type', 'Access-Control-Allow-Methods': 'GET,POST,DELETE,OPTIONS' }
    const reply = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', headers, body: status === 204 ? '' : JSON.stringify(data) })
    if (request.method() === 'OPTIONS') return reply(null, 204)
    if (path === '/api/v1/users/me') return state.failMe ? reply({ error: { message: 'unavailable' } }, 503) : state.user ? reply(state.user) : reply({}, 401)
    if (path === '/api/v1/users') return reply({ id: 'new', username: request.postDataJSON().username }, 201)
    if (path === '/api/v1/sessions') {
      const data = request.postDataJSON()
      if (data.password !== 'Example-password-123!') return reply({ error: { message: '用户名或密码错误' } }, 401)
      state.user = { id: data.username, username: data.username }
      return reply({ user: state.user }, 201)
    }
    if (path === '/api/v1/sessions/current') { if (state.failLogout) return reply({}, 503); state.user = null; return reply(null, 204) }
    if (!state.user) return reply({}, 401)
    if (path === '/menu/plan') { state.plans++; return reply({ dish_list: [{ id: 1, name: '清炒土豆丝', intent: '少油做法' }] }) }
    if (path === '/memory/confirm' || path === '/memory') return reply({ memory: state.memory })
    if (path === '/memory/clear') { state.clears++; state.memory = {}; return reply({ memory: {} }) }
    if (path === '/menu/stream') { state.streams++; return route.fulfill({ headers, contentType: 'text/event-stream', body: 'data: {"type":"done"}\n\n' }) }
    return reply({}, 404)
  })
  return state
}
async function login(page, name = 'alice') {
  await page.getByLabel('用户名', { exact: true }).fill(name)
  await page.getByLabel('密码', { exact: true }).fill('Example-password-123!')
  await page.getByRole('dialog').getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByRole('button', { name: `${name}的用户画像` })).toBeVisible()
}

test('guest intent resumes once; profile, confirmation, stream and logout work', async ({ page }) => {
  const state = await backend(page)
  await page.goto('/')
  await page.getByLabel('告诉我用餐需求或修改意见').fill('两人吃土豆，少油')
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  expect(state.plans).toBe(0)
  await login(page)
  await expect(page.getByRole('heading', { name: '建议方案' })).toBeVisible()
  expect(state.plans).toBe(1)
  await page.getByRole('button', { name: 'alice的用户画像' }).click()
  await expect(page.getByRole('heading', { name: '饮食偏好' })).toBeVisible()
  await page.getByRole('button', { name: '清空长期记忆', exact: true }).click()
  await page.getByRole('button', { name: '确认清空', exact: true }).click()
  await expect.poll(() => state.clears).toBe(1)
  await page.getByRole('button', { name: '关闭用户画像' }).click()
  await page.getByRole('button', { name: '同意生成', exact: true }).click()
  await expect(page).toHaveURL(/menu-progress/)
  await expect.poll(() => state.streams).toBe(1)
  await page.getByRole('button', { name: 'alice的用户画像' }).click()
  await page.getByRole('button', { name: '退出登录', exact: true }).click()
  await expect(page).toHaveURL('http://localhost:5187/')
  await page.goBack()
  await expect(page.getByText('清炒土豆丝', { exact: true })).toHaveCount(0)
  expect(state.streams).toBe(1)
})

test('cancel retains draft and manual login does not replay cancelled intent', async ({ page }) => {
  const state = await backend(page)
  await page.goto('/')
  await page.getByLabel('告诉我用餐需求或修改意见').fill('想吃鸡蛋')
  await page.getByRole('button', { name: '发送消息' }).click()
  await page.getByRole('button', { name: '关闭登录弹窗' }).click()
  await expect(page.getByLabel('告诉我用餐需求或修改意见')).toHaveValue('想吃鸡蛋')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await login(page)
  await expect(page.getByLabel('告诉我用餐需求或修改意见')).toHaveValue('想吃鸡蛋')
  expect(state.plans).toBe(0)
})

test('registration returns to login and service failure offers recovery', async ({ page }) => {
  const state = await backend(page)
  state.failMe = true
  await page.goto('/')
  await expect(page.getByText('暂时无法确认登录状态，请重试。')).toBeVisible()
  state.failMe = false
  await page.getByRole('button', { name: '连接失败 · 重试' }).click()
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.getByRole('button', { name: '还没有账号？注册' }).click()
  await page.getByLabel('用户名', { exact: true }).fill('alice')
  await page.getByLabel('密码', { exact: true }).fill('Example-password-123!')
  await page.getByLabel('确认密码', { exact: true }).fill('Example-password-123!')
  await page.getByRole('button', { name: '注册', exact: true }).click()
  await expect(page.getByText('注册成功，请登录。')).toBeVisible()
  await expect(page.getByLabel('密码', { exact: true })).toHaveValue('')
  await login(page)
  state.failLogout = true
  await page.getByRole('button', { name: 'alice的用户画像' }).click()
  await page.getByRole('button', { name: '退出登录', exact: true }).click()
  await expect(page.getByText(/退出失败，请重试/)).toBeVisible()
  await expect(page.getByRole('button', { name: '退出登录', exact: true })).toBeVisible()
})

test('expired confirmation cannot be submitted under a different account', async ({ page }) => {
  const state = await backend(page)
  state.user = { id: 'alice', username: 'alice' }
  await page.goto('/')
  await page.getByLabel('告诉我用餐需求或修改意见').fill('土豆晚餐')
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(page.getByRole('heading', { name: '建议方案' })).toBeVisible()
  state.user = null
  await page.getByRole('button', { name: '同意生成', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await login(page, 'bob')
  await expect(page.getByText('清炒土豆丝', { exact: true })).toHaveCount(0)
  expect(state.streams).toBe(0)
  expect(state.plans).toBe(1)
})

test('focus revalidation detects account change and removes previous data', async ({ page }) => {
  const state = await backend(page)
  state.user = { id: 'alice', username: 'alice' }
  await page.goto('/')
  await page.getByLabel('告诉我用餐需求或修改意见').fill('A 的土豆晚餐')
  await page.getByRole('button', { name: '发送消息' }).click()
  await expect(page.getByRole('heading', { name: '建议方案' })).toBeVisible()
  state.user = { id: 'bob', username: 'bob' }
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await expect(page.getByRole('button', { name: 'bob的用户画像' })).toBeVisible()
  await expect(page.getByText('A 的土豆晚餐', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '建议方案' })).toHaveCount(0)
})

test('mobile login supports Escape, focus recovery and readable viewport', async ({ page }) => {
  await backend(page)
  await page.setViewportSize({ width: 390, height: 600 })
  await page.goto('/')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await expect(page.getByLabel('用户名', { exact: true })).toBeFocused()
  await page.screenshot({ path: 'test-results/mobile-login.png' })
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '登录', exact: true })).toBeFocused()
})

test('stalled login check becomes a retryable error instead of loading forever', async ({ page }) => {
  await backend(page)
  let stalled = true
  await page.route('http://localhost:8000/api/v1/users/me', async route => {
    if (stalled) return
    await route.fallback()
  })
  await page.goto('/')
  await expect(page.getByText('正在检查登录…')).toBeVisible()
  await expect(page.getByText('登录状态检查超时，请确认后端服务已启动后重试。')).toBeVisible({ timeout: 15000 })
  stalled = false
  await page.getByRole('button', { name: '连接失败 · 重试' }).click()
  await expect(page.getByRole('button', { name: '登录', exact: true })).toBeVisible()
})
