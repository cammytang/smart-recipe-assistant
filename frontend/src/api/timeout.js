// Cover both response headers and body parsing. A stalled server must not lock the UI.
export async function withTimeout(operation, timeoutMs) {
  const controller = new AbortController()
  let timer
  try {
    return await Promise.race([
      Promise.resolve().then(() => operation(controller.signal)),
      new Promise((_, reject) => {
        timer = setTimeout(() => {
          reject(new DOMException('登录状态检查超时，请确认后端服务已启动后重试。', 'TimeoutError'))
          controller.abort()
        }, timeoutMs)
      }),
    ])
  } finally { clearTimeout(timer) }
}
