import { describe, expect, it, vi } from 'vitest'
import { createCubismParameterAdapter } from './performanceProfile'

describe('Live2D performance model adapter', () => {
  it('reads and writes known Cubism parameters with model bounds', () => {
    const set = vi.fn()
    const coreModel = {
      getParameterIndex: (name: string) => (name === 'ParamBrowLY' ? 2 : -1),
      getParameterValueByIndex: () => 0.25,
      setParameterValueByIndex: set,
      getParameterMinimumValue: () => -0.5,
      getParameterMaximumValue: () => 0.5,
    }
    const adapter = createCubismParameterAdapter(coreModel)

    expect(adapter.read('ParamBrowLY')).toBe(0.25)
    expect(adapter.read('missing')).toBe(0)
    adapter.write('ParamBrowLY', 2)
    adapter.write('missing', 1)

    expect(set).toHaveBeenCalledOnce()
    expect(set).toHaveBeenCalledWith(2, 0.5)
  })
})
