import { test } from 'node:test'
import assert from 'node:assert/strict'
import { Session } from './session.js'
const ok = data => ({ status: 200, json: async () => data })
const user = id => ({ id, username: id })
const failure = status => Object.assign(new Error('failed'), { status })
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }

test('guest intent is consumed once, cancellation preserves no auto action', async () => {
  const session = new Session(async () => ok({ user: user('a') }))
  session.transition('anonymous', null)
  assert.equal(session.require({ kind: 'plan', payload: { text: 'potato' } }), false)
  session.require({ kind: 'plan', payload: { text: 'duplicate' } })
  await session.authenticate('login', {})
  assert.equal(session.takeIntent().payload.text, 'potato')
  assert.equal(session.takeIntent(), null)
  session.transition('anonymous', null)
  session.require({ kind: 'plan', payload: {} })
  session.closeLogin()
  await session.authenticate('login', {})
  assert.equal(session.takeIntent(), null)
})

test('business 401 preserves owner-bound intent but login 401 does not expire user', async () => {
  let loginFails = false
  const session = new Session(async path => {
    if (path === '/api/v1/sessions') { if (loginFails) throw failure(401); return ok({ user: user('b') }) }
    throw failure(401)
  })
  session.transition('authenticated', user('a'))
  await assert.rejects(session.request('/menu/plan', {}, { kind: 'plan', payload: {} }), { name: 'AbortError' })
  assert.equal(session.view.pending.ownerUserId, 'a')
  assert.equal(session.view.dialog, true)
  await session.authenticate('login', {})
  assert.equal(session.takeIntent(), null)
  loginFails = true
  await assert.rejects(session.authenticate('login', {}))
  assert.equal(session.view.user.id, 'b')
})

test('late response for A cannot update B even if transport ignores AbortSignal', async () => {
  const response = deferred()
  const session = new Session(() => response.promise)
  session.transition('authenticated', user('a'))
  const request = session.request('/memory')
  session.transition('authenticated', user('b'))
  response.resolve(ok({ private: 'A' }))
  await assert.rejects(request, { name: 'AbortError' })
})

test('late JSON body is checked after identity changes', async () => {
  const body = deferred()
  const session = new Session(async () => ({ status: 200, json: () => body.promise }))
  session.transition('authenticated', user('a'))
  const request = session.request('/memory')
  await Promise.resolve()
  session.transition('authenticated', user('b'))
  body.resolve({ private: 'A' })
  await assert.rejects(request, { name: 'AbortError' })
})

test('network error during session recovery is not anonymous; focus does not rotate same user', async () => {
  let broken = true
  const session = new Session(async () => { if (broken) throw failure(503); return ok(user('a')) })
  await session.check()
  assert.equal(session.view.status, 'error')
  broken = false
  await session.check()
  const epoch = session.view.epoch
  await session.check()
  assert.equal(session.view.epoch, epoch)
})

test('closing a pending login rechecks cookie but never restores its cancelled action', async () => {
  const response = deferred()
  const session = new Session(path => path === '/api/v1/users/me' ? Promise.resolve(ok(user('a'))) : response.promise)
  session.transition('anonymous', null)
  session.require({ kind: 'plan', payload: {} })
  const login = session.authenticate('login', {})
  session.closeLogin()
  response.resolve(ok({ user: user('a') }))
  await login
  assert.equal(session.view.user.id, 'a')
  assert.equal(session.view.pending, null)
})

test('logout failure never announces anonymous; success clears private state', async () => {
  let fail = true
  const session = new Session(async () => { if (fail) throw failure(503); return { status: 204 } })
  session.transition('authenticated', user('a'))
  const oldScope = session.view.scope
  await session.logout()
  assert.equal(session.view.status, 'authenticated')
  assert.match(session.view.error, /退出失败/)
  assert.notEqual(session.view.scope, oldScope)
  fail = false
  await session.logout()
  assert.equal(session.view.status, 'anonymous')
  assert.equal(session.view.profile, null)
})

test('stream task cannot be automatically started twice in the same session', () => {
  const session = new Session(() => {})
  assert.equal(session.claimStream('task'), true)
  assert.equal(session.claimStream('task'), false)
})

test('stalled session request times out, aborts transport and allows retry', async () => {
  let signal
  let stalled = true
  const session = new Session(async (_path, options) => {
    signal = options.signal
    if (stalled) return new Promise(() => {})
    return ok(user('a'))
  }, { checkTimeoutMs: 15 })
  await session.check()
  assert.equal(session.view.status, 'error')
  assert.match(session.view.error, /超时/)
  assert.equal(signal.aborted, true)
  assert.equal(session.checking, null)
  stalled = false
  await session.check()
  assert.equal(session.view.status, 'authenticated')
})

test('stalled JSON response body also times out and cannot revive a later identity', async () => {
  const body = deferred()
  const session = new Session(async () => ({ status: 200, json: () => body.promise }), { checkTimeoutMs: 15 })
  await session.check()
  assert.equal(session.view.status, 'error')
  session.transition('authenticated', user('b'))
  body.resolve(user('a'))
  await Promise.resolve()
  await Promise.resolve()
  assert.equal(session.view.user.id, 'b')
})
