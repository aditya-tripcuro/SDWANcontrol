import { describe, it, expect } from 'vitest'
import { sseManager } from '../../src/api/sse'
import { MockEventSource } from './setup'

describe('SseManager', () => {
  it('connected false before connect and true after onopen', () => {
    const token = 'tok'
    sseManager.connect(token)
    expect(sseManager.connected).toBe(true)
    sseManager.disconnect()
  })

  it('dispatches events to callbacks and parses JSON', () => {
    const token = 'tok'
    sseManager.connect(token)
    const inst = MockEventSource.instances[0]
    let received: any = null
    const cb = (d: unknown) => { received = d }
    sseManager.on('status', cb)
    inst.emit('status', { mode: 'RUNNING' })
    expect(received).toEqual({ mode: 'RUNNING' })
    sseManager.off('status', cb)
    sseManager.disconnect()
  })
})
