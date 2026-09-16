import { withTimeout } from '../api/timeout.js'

// Framework-independent session coordinator. No user data is persisted in browser storage.
const cancelled = () => new DOMException('请求所属的身份已失效', 'AbortError')

export class Session {
  constructor(fetcher, { checkTimeoutMs = 10000 } = {}) {
    this.checkTimeoutMs = checkTimeoutMs
    this.fetcher = fetcher
    this.view = { status: 'checking', user: null, epoch: 0, pageVersion: 0, scope: '', dialog: false, drawer: false, profile: null, profileStatus: 'idle', error: '', logoutBusy: false, pending: null }
    this.streamClaims = new Set()
    this.listeners = new Set()
    this.controllers = new Set()
    this.checking = null
    this.mutation = false
    this.mutationVersion = 0
    this.dialogVersion = 0
    this.profileVersion = 0
    this.notifyPeers = () => {}
  }
  subscribe = listener => { this.listeners.add(listener); return () => this.listeners.delete(listener) }
  snapshot = () => this.view
  patch(values) { this.view = { ...this.view, ...values }; this.listeners.forEach(listener => listener()) }
  claimStream(id) { if (this.streamClaims.has(id)) return false; this.streamClaims.add(id); return true }
  setNotifier(callback) { this.notifyPeers = callback }
  abort() { this.controllers.forEach(controller => controller.abort()); this.controllers.clear() }
  transition(status, user, extra = {}) {
    const changed = this.view.status === 'authenticated' !== (status === 'authenticated') || this.view.user?.id !== user?.id
    if (changed) {
      this.abort()
      this.streamClaims.clear()
      this.profileVersion++
      this.patch({ epoch: this.view.epoch + 1, pageVersion: this.view.pageVersion + (this.view.user ? 1 : 0), scope: status === 'authenticated' ? crypto.randomUUID() : '', profile: null, profileStatus: 'idle', drawer: false })
    }
    this.patch({ status, user, ...extra })
  }
  valid(epoch, userId) { return this.view.status === 'authenticated' && !this.view.logoutBusy && this.view.epoch === epoch && this.view.user?.id === userId }
  async check() {
    if (this.mutation) return
    if (this.checking) return this.checking
    if (this.view.status === 'error') this.patch({ status: 'checking', error: '' })
    const version = this.mutationVersion
    const epoch = this.view.epoch
    this.checking = (async () => {
      try {
        const user = await withTimeout(async signal => {
          const response = await this.fetcher('/api/v1/users/me', { signal })
          return response.json()
        }, this.checkTimeoutMs)
        if (version !== this.mutationVersion || epoch !== this.view.epoch) return
        const pending = this.view.pending
        this.transition('authenticated', user, { error: '', pending: pending?.ownerUserId && pending.ownerUserId !== user.id ? null : pending })
      } catch (error) {
        if (version !== this.mutationVersion || epoch !== this.view.epoch) return
        if (error.status === 401) {
          this.transition('anonymous', null, { error: '', dialog: Boolean(this.view.pending) || this.view.dialog })
        } else {
          this.transition('error', null, { error: error.name === 'TimeoutError' ? error.message : '暂时无法确认登录状态，请重试。' })
        }
      } finally { this.checking = null }
    })()
    return this.checking
  }
  openLogin() { this.focusReturn = globalThis.document?.activeElement; this.patch({ dialog: true }) }
  closeLogin() { this.dialogVersion++; this.patch({ dialog: false, pending: null }) }
  cancelIntent() { this.patch({ pending: null }) }
  require(intent) {
    if (this.view.status === 'authenticated' && !this.view.logoutBusy) return true
    if (this.view.logoutBusy) return false
    if (!this.view.pending) this.patch({ pending: { ...intent, id: crypto.randomUUID(), ownerUserId: intent.ownerUserId || null } })
    if (this.view.status === 'anonymous') this.openLogin()
    return false
  }
  takeIntent() {
    const pending = this.view.pending
    if (this.view.status !== 'authenticated' || !pending) return null
    this.patch({ pending: null })
    return !pending.ownerUserId || pending.ownerUserId === this.view.user.id ? pending : null
  }
  async authenticate(mode, credentials) {
    if (this.mutation) throw new Error('上一笔认证请求尚未结束，请稍后重试。')
    this.mutation = true
    this.mutationVersion++
    const dialogVersion = this.dialogVersion
    try {
      const response = await this.fetcher(mode === 'register' ? '/api/v1/users' : '/api/v1/sessions', { method: 'POST', body: JSON.stringify(credentials) })
      const data = await response.json()
      if (mode === 'login') {
        if (dialogVersion !== this.dialogVersion) return
        const pending = this.view.pending
        this.transition('authenticated', data.user, { dialog: false, error: '', pending: pending?.ownerUserId && pending.ownerUserId !== data.user.id ? null : pending })
        this.notifyPeers()
      }
      return data
    } finally {
      this.mutation = false
      // Closing a dialog cannot cancel a Set-Cookie already sent by the server.
      if (dialogVersion !== this.dialogVersion) await this.check()
    }
  }
  expire(intent, epoch, userId) {
    if (!this.valid(epoch, userId)) return
    const pending = intent ? { ...intent, id: crypto.randomUUID(), ownerUserId: userId } : this.view.pending
    this.transition('anonymous', null, { dialog: true, pending, error: '' })
  }
  async open(path, options = {}, intent = null) {
    const { epoch, user } = this.view
    if (!this.valid(epoch, user?.id)) throw cancelled()
    const controller = new AbortController()
    this.controllers.add(controller)
    const externalAbort = () => controller.abort()
    options.signal?.addEventListener('abort', externalAbort, { once: true })
    if (options.signal?.aborted) controller.abort()
    const release = () => { this.controllers.delete(controller); options.signal?.removeEventListener('abort', externalAbort) }
    const check = () => { if (controller.signal.aborted || !this.valid(epoch, user.id)) throw cancelled() }
    try {
      const response = await this.fetcher(path, { ...options, signal: controller.signal })
      check()
      return { response, check, release, signal: controller.signal }
    } catch (error) {
      release()
      if (controller.signal.aborted || !this.valid(epoch, user.id)) throw cancelled()
      if (error.status === 401) { this.expire(intent, epoch, user.id); throw cancelled() }
      throw error
    }
  }
  async request(path, options, intent) {
    const ticket = await this.open(path, options, intent)
    try {
      const value = ticket.response.status === 204 ? null : await ticket.response.json()
      ticket.check()
      return value
    } finally { ticket.release() }
  }
  async loadProfile() {
    const version = ++this.profileVersion
    this.patch({ profileStatus: 'loading', error: '' })
    try {
      const data = await this.request('/memory')
      if (version === this.profileVersion) this.patch({ profile: data.memory, profileStatus: 'ready' })
    } catch (error) {
      if (error.name !== 'AbortError' && version === this.profileVersion) this.patch({ profileStatus: 'error', error: error.message })
    }
  }
  async clearProfile() {
    ++this.profileVersion
    const data = await this.request('/memory/clear', { method: 'POST' })
    this.patch({ profile: data.memory, profileStatus: 'ready' })
  }
  updateProfile(memory) { ++this.profileVersion; this.patch({ profile: memory, profileStatus: 'ready' }) }
  async logout() {
    if (this.mutation) return
    this.mutation = true
    this.mutationVersion++
    this.abort()
    this.profileVersion++
    this.patch({ logoutBusy: true, epoch: this.view.epoch + 1, pageVersion: this.view.pageVersion + 1, scope: crypto.randomUUID(), pending: null, error: '' })
    try {
      await this.fetcher('/api/v1/sessions/current', { method: 'DELETE' })
      this.transition('anonymous', null, { dialog: false, drawer: false, profile: null, pending: null })
      this.notifyPeers()
    } catch {
      this.patch({ error: '退出失败，请重试。已停止的生成不会自动恢复。' })
    } finally { this.mutation = false; this.patch({ logoutBusy: false }) }
  }
  dispose() { this.abort() }
}
