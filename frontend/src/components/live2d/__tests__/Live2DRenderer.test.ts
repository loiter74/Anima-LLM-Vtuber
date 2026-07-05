import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick, ref } from 'vue'
import Live2DRenderer from '@/components/live2d/Live2DRenderer.vue'

const mockIsMobile = vi.hoisted(() => ({ value: false, __v_isRef: true }))

// Create a mock for useLive2D with controllable state
const mockLive2DState = {
  isLoaded: ref(false),
  isLoading: ref(false),
  loadError: ref(''),
  modelInfo: ref<Record<string, string> | null>(null),
  isDragging: ref(false),
  init: vi.fn().mockResolvedValue(undefined),
  loadModel: vi.fn().mockResolvedValue(undefined),
  resetView: vi.fn(),
  zoom: vi.fn(),
  startDrag: vi.fn(),
  onDrag: vi.fn(),
  stopDrag: vi.fn(),
  focus: vi.fn(),
  handleResize: vi.fn(),
  executeAction: vi.fn(),
  setExpression: vi.fn(),
  playMotion: vi.fn(),
  setMouthTarget: vi.fn(),
  stopAudio: vi.fn(),
  destroy: vi.fn(),
  setScaleStrategy: vi.fn(),
}

vi.mock('@/components/live2d/useLive2D', () => ({
  useLive2D: () => mockLive2DState,
  MODEL_PATH: 'live2d/hiyori/Hiyori.model3.json',
}))

vi.mock('@/composables/useMobile', () => ({
  useMobile: () => ({ isMobile: mockIsMobile }),
}))

function createWrapper() {
  return mount(Live2DRenderer, {
    global: {
      stubs: {
        SubtitleOverlay: true,
      },
    },
    attachTo: document.body,
  })
}

describe('Live2DRenderer', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Reset all reactive refs
    mockLive2DState.isLoaded.value = false
    mockLive2DState.isLoading.value = false
    mockLive2DState.loadError.value = ''
    mockLive2DState.modelInfo.value = null
    mockLive2DState.isDragging.value = false
    mockIsMobile.value = false
  })

  it('renders canvas element', () => {
    const wrapper = createWrapper()
    expect(wrapper.find('canvas').exists()).toBe(true)
  })

  it('initializes and loads the default model on desktop', async () => {
    createWrapper()
    await flushPromises()

    expect(mockLive2DState.init).toHaveBeenCalledTimes(1)
    expect(mockLive2DState.loadModel).toHaveBeenCalledWith('live2d/hiyori/Hiyori.model3.json')
  })

  it('initializes Live2D by default on mobile', async () => {
    mockIsMobile.value = true

    const wrapper = createWrapper()
    await flushPromises()

    expect(wrapper.find('canvas').exists()).toBe(true)
    expect(wrapper.text()).toContain('Live2D ON')
    expect(wrapper.text()).not.toContain('Live2D 已暂停')
    expect(mockLive2DState.init).toHaveBeenCalledTimes(1)
    expect(mockLive2DState.loadModel).toHaveBeenCalledWith('live2d/hiyori/Hiyori.model3.json')
  })

  it('can pause Live2D on mobile without showing a load error', async () => {
    mockIsMobile.value = true
    mockLive2DState.loadError.value = 'PixiJS 未初始化，请刷新页面重试'

    const wrapper = createWrapper()
    const toggle = wrapper.find('button')
    await toggle.trigger('click')
    await nextTick()

    expect(wrapper.find('canvas').exists()).toBe(false)
    expect(wrapper.text()).toContain('Live2D OFF')
    expect(wrapper.text()).not.toContain('模型加载失败')
    expect(wrapper.text()).not.toContain('PixiJS 未初始化')
  })

  describe('idle state (no model)', () => {
    it('shows idle message when not loaded, not loading, no error', () => {
      const wrapper = createWrapper()
      expect(wrapper.text()).toContain('未加载 Live2D 模型')
    })

    it('does not show reset button when model not loaded', () => {
      const wrapper = createWrapper()
      const resetBtn = wrapper.find('button')
      expect(resetBtn.exists()).toBe(false)
    })

    it('does not show loading state', () => {
      const wrapper = createWrapper()
      expect(wrapper.text()).not.toContain('加载 Live2D 模型中')
    })

    it('does not show error state', () => {
      const wrapper = createWrapper()
      expect(wrapper.text()).not.toContain('模型加载失败')
    })
  })

  describe('loading state', () => {
    beforeEach(() => {
      mockLive2DState.isLoading.value = true
    })

    it('shows loading message', () => {
      const wrapper = createWrapper()
      expect(wrapper.text()).toContain('加载 Live2D 模型中')
    })

    it('does not show idle message', () => {
      const wrapper = createWrapper()
      expect(wrapper.text()).not.toContain('未加载 Live2D 模型')
    })

    it('does not show error state', () => {
      const wrapper = createWrapper()
      expect(wrapper.text()).not.toContain('模型加载失败')
    })
  })

  describe('loaded state', () => {
    beforeEach(() => {
      mockLive2DState.isLoaded.value = true
      mockLive2DState.modelInfo.value = {
        strategy: 'fit',
        userScale: '2.59',
        position: '(280, 720)',
        canvas: '800x600',
      }
    })

    it('shows reset button', () => {
      const wrapper = createWrapper()
      const resetBtn = wrapper.find('button')
      expect(resetBtn.exists()).toBe(true)
      expect(resetBtn.text()).toContain('复位')
    })

    it('shows zoom and position info', () => {
      const wrapper = createWrapper()
      expect(wrapper.text()).toContain('2.59')
      expect(wrapper.text()).toContain('(280, 720)')
    })

    it('does not show idle message', () => {
      const wrapper = createWrapper()
      expect(wrapper.text()).not.toContain('未加载 Live2D 模型')
    })

    it('reset button click calls resetView', async () => {
      const wrapper = createWrapper()
      const resetBtn = wrapper.find('button')
      await resetBtn.trigger('click')
      expect(mockLive2DState.resetView).toHaveBeenCalled()
    })

    it('does not show error state', () => {
      const wrapper = createWrapper()
      expect(wrapper.text()).not.toContain('模型加载失败')
    })
  })

  describe('error state', () => {
    beforeEach(() => {
      mockLive2DState.loadError.value = 'Failed to load model'
    })

    it('shows error message', () => {
      const wrapper = createWrapper()
      expect(wrapper.text()).toContain('模型加载失败')
    })

    it('does not show loading state', () => {
      const wrapper = createWrapper()
      expect(wrapper.text()).not.toContain('加载 Live2D 模型中')
    })

    it('does not show idle message', () => {
      const wrapper = createWrapper()
      expect(wrapper.text()).not.toContain('未加载 Live2D 模型')
    })
  })

  describe('mouse interactions', () => {
    beforeEach(() => {
      mockLive2DState.isLoaded.value = true
      mockLive2DState.modelInfo.value = {
        strategy: 'fit',
        userScale: '2.59',
        position: '(280, 720)',
        canvas: '800x600',
      }
    })

    it('calls startDrag on mousedown', async () => {
      const wrapper = createWrapper()
      const container = wrapper.find('div.relative')
      await container.trigger('mousedown', { clientX: 100, clientY: 200 })
      expect(mockLive2DState.startDrag).toHaveBeenCalledWith(100, 200)
    })

    it('shows dragging indicator when dragging', () => {
      mockLive2DState.isDragging.value = true
      const wrapper = createWrapper()
      expect(wrapper.text()).toContain('拖拽移动中')
    })

    it('hides dragging indicator when not dragging', () => {
      const wrapper = createWrapper()
      expect(wrapper.text()).not.toContain('拖拽移动中')
    })

    it('calls stopDrag on mouseup', async () => {
      const wrapper = createWrapper()
      const container = wrapper.find('div.relative')
      await container.trigger('mouseup')
      expect(mockLive2DState.stopDrag).toHaveBeenCalled()
    })

    it('calls stopDrag on mouseleave', async () => {
      const wrapper = createWrapper()
      const container = wrapper.find('div.relative')
      await container.trigger('mouseleave')
      expect(mockLive2DState.stopDrag).toHaveBeenCalled()
    })

    it('calls focus on mousemove when not dragging', async () => {
      const wrapper = createWrapper()
      const container = wrapper.find('div.relative')
      await container.trigger('mousemove', { clientX: 300, clientY: 400 })
      expect(mockLive2DState.focus).toHaveBeenCalled()
    })
  })

  it('renders SubtitleOverlay stub', () => {
    const wrapper = createWrapper()
    const overlay = wrapper.findComponent({ name: 'SubtitleOverlay' })
    expect(overlay.exists()).toBe(true)
  })

  it('renders canvas with full width/height classes', () => {
    const wrapper = createWrapper()
    const canvas = wrapper.find('canvas')
    expect(canvas.classes()).toContain('w-full')
    expect(canvas.classes()).toContain('h-full')
  })
})
