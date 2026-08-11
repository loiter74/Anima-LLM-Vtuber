import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import PlaybackControls from './PlaybackControls.vue'

describe('PlaybackControls', () => {
  it('uses media metadata when a recent item has no stored duration', async () => {
    const wrapper = mount(PlaybackControls, {
      props: { duration: 0, audioUrl: '/full-song.wav', label: 'RVC 混音' },
    })
    const audio = wrapper.get('audio').element as HTMLAudioElement
    vi.spyOn(audio, 'duration', 'get').mockReturnValue(254)

    await wrapper.get('audio').trigger('loadedmetadata')

    expect(wrapper.text()).toContain('0:00 / 4:14')
    wrapper.unmount()
  })
})
