import "@testing-library/jest-dom"
import { server } from "./mocks/server"

class MockEventSource {
  static instances: MockEventSource[] = []
  url: string
  onopen: (() => void) | null = null
  onerror: ((e: Event) => void) | null = null
  private handlers: Record<string, ((e: MessageEvent) => void)[]> = {}

  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
    setTimeout(() => this.onopen?.(), 0)
  }
  addEventListener(event: string, cb: (e: MessageEvent) => void) {
    this.handlers[event] = [...(this.handlers[event] ?? []), cb]
  }
  removeEventListener(event: string, cb: (e: MessageEvent) => void) {
    this.handlers[event] = (this.handlers[event] ?? []).filter(h => h !== cb)
  }
  emit(event: string, data: unknown) {
    const msg = new MessageEvent(event, { data: JSON.stringify(data) })
    this.handlers[event]?.forEach(cb => cb(msg))
  }
  close() {}
}
;(globalThis as unknown as Record<string, unknown>).EventSource = MockEventSource
export { MockEventSource }

beforeAll(() => server.listen({ onUnhandledRequest: "warn" }))
afterEach(() => {
  server.resetHandlers()
  MockEventSource.instances.length = 0
})
afterAll(() => server.close())
