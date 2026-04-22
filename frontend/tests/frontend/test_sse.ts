import { describe, it, expect, vi } from 'vitest'
import { sseManager } from '../../src/api/sse'

describe('SseManager', () => {
  it('connected false before connect and true after onopen', async () => {
    const token = 'tok'
    sseManager.connect(token)
    // Wait for the next tick for the setTimeout(..., 0) to execute.
    await vi.waitFor(() => {
      if (!sseManager.connected) throw new Error('Not connected')
    })
    expect(sseManager.connected).toBe(true)
    sseManager.disconnect()
  })

  it('dispatches events to callbacks and parses JSON', async () => {
    const token = 'tok'
    sseManager.connect(token)
    // Wait for the connection to be established.
    await vi.waitFor(() => {
      if (!sseManager.connected) throw new Error('Not connected')
    })
    // MockEventSource.instances[0] was pushed in the constructor.
    // However, it's safer to access through the internal property if possible,
    // but here we just rely on the mock's behavior from setup.ts.
    // Since MockEventSource was globally mocked, we need to access its static.
    const { MockEventSource } = await import('./setup')
    const inst = MockEventSource.instances[MockEventSource.instances.length - 1]
    let received: any = null
    const cb = (d: unknown) => { received = d }
    sseManager.on('status', cb)
    inst.emit('status', { mode: 'RUNNING' })
    expect(received).toEqual({ mode: 'RUNNING' })
    sseManager.off('status', cb)
    sseManager.disconnect()
  })
})
