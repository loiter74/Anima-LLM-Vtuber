import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useSocket } from '@/composables/useSocket'
import { Events } from '@/constants/socket-events'

export interface MemeItem {
  id: string
  text: string
  context_hint: string
  tags: string[]
  source_platform: string
  base_score: number
  cognitive_analysis?: {
    humor_mechanism: string
    emotional_tone: string
    persona_fit_score: number
    source_url: string
  }
}

export const useMemeReviewStore = defineStore('memeReview', () => {
  const memes = ref<MemeItem[]>([])
  const currentIndex = ref(0)
  const loading = ref(false)
  const feedback = ref('')
  const feedbackVisible = ref(false)
  const goodCount = ref(0)
  const badCount = ref(0)
  const datasetReady = ref(false)

  const currentMeme = computed(() => memes.value[currentIndex.value] ?? null)
  const total = computed(() => memes.value.length)
  const progress = computed(() => `${currentIndex.value + 1} / ${total.value}`)
  const isDone = computed(() => total.value > 0 && currentIndex.value >= total.value)

  const { socket: sock } = useSocket()

  function fetchMemes(sourcePlatform = '') {
    if (!sock) return
    loading.value = true
    memes.value = []
    currentIndex.value = 0
    sock.emit(Events.MEME.LIST, { source_platform: sourcePlatform, limit: 50 })

    sock.once(Events.MEME.LIST, (data: { memes: MemeItem[]; error?: string }) => {
      loading.value = false
      if (data.error) {
        console.warn('[memeReview]', data.error)
        return
      }
      memes.value = data.memes || []
      goodCount.value = 0
      badCount.value = 0
    })
  }

  function voteGood() {
    const meme = currentMeme.value
    if (!meme) return
    submitReview(meme.id, 'good')
  }

  function voteBad() {
    const meme = currentMeme.value
    if (!meme) return
    submitReview(meme.id, 'bad')
  }

  function submitReview(memeId: string, status: 'good' | 'bad') {
    sock.emit(Events.MEME.REVIEW, { meme_id: memeId, status })
    sock.once(Events.MEME.REVIEW, (data: { ok: boolean; feedback?: string; error?: string }) => {
      if (data.ok) {
        if (status === 'good') goodCount.value++
        else badCount.value++

        if (data.feedback) {
          feedback.value = data.feedback
          feedbackVisible.value = true
          setTimeout(() => {
            feedbackVisible.value = false
            nextMeme()
          }, 2500)
        } else {
          nextMeme()
        }
      } else {
        console.warn('[memeReview] Review failed:', data.error)
      }
    })
  }

  function nextMeme() {
    if (currentIndex.value < total.value - 1) {
      currentIndex.value++
    } else {
      currentIndex.value = total.value // marks as done
    }
  }

  function prevMeme() {
    if (currentIndex.value > 0) {
      currentIndex.value--
    }
  }

  function exportDataset() {
    sock.emit(Events.MEME.DATASET, {})
    sock.once(Events.MEME.DATASET, (data: { memes: any[]; error?: string }) => {
      if (data.error) {
        console.warn('[memeReview] Export error:', data.error)
        return
      }
      const json = JSON.stringify(data.memes, null, 2)
      const blob = new Blob([json], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'meme_dataset.json'
      a.click()
      URL.revokeObjectURL(url)
      datasetReady.value = true
    })
  }

  return {
    memes, currentIndex, loading, feedback, feedbackVisible,
    goodCount, badCount, datasetReady,
    currentMeme, total, progress, isDone,
    fetchMemes, voteGood, voteBad, nextMeme, prevMeme, exportDataset, socket: sock,
  }
})
