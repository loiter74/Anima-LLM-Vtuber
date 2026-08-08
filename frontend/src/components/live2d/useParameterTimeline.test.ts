import { beforeEach, describe, expect, it, vi } from 'vitest'

const getModel = vi.hoisted(() => vi.fn())

vi.mock('./useLive2DModel', () => ({ getModel }))

import { setParam } from './useParameterTimeline'

describe('setParam', () => {
  const setParameterValueByIndex = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('adapts the legacy mouth-form parameter to Mao mouth corners', () => {
    const indices: Record<string, number> = {
      ParamMouthUp: 21,
      ParamMouthDown: 22,
    }
    getModel.mockReturnValue({
      internalModel: {
        coreModel: {
          getParameterIndex: (name: string) => indices[name] ?? -1,
          setParameterValueByIndex,
        },
      },
    })

    setParam('ParamMouthForm', -0.4)

    expect(setParameterValueByIndex).toHaveBeenCalledWith(21, 0)
    expect(setParameterValueByIndex).toHaveBeenCalledWith(22, 0.4)
  })

  it('keeps a model-native mouth-form parameter when available', () => {
    getModel.mockReturnValue({
      internalModel: {
        coreModel: {
          getParameterIndex: (name: string) => (name === 'ParamMouthForm' ? 7 : -1),
          setParameterValueByIndex,
        },
      },
    })

    setParam('ParamMouthForm', 0.3)

    expect(setParameterValueByIndex).toHaveBeenCalledOnce()
    expect(setParameterValueByIndex).toHaveBeenCalledWith(7, 0.3)
  })
})
