import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getSocket } from '@/composables/useSocket'
import { Events } from '@/constants/socket-events'

/** Wiki 页面条目（匹配 backend on_get_wiki_pages 返回） */
export interface WikiPageEntry {
  path: string
  title: string
  page_type: string
  content: string
  tags: string[]
  updated_at: string
}

const typeOptions: { key: string | null; label: string }[] = [
  { key: null, label: '全部' },
  { key: 'entity', label: '实体' },
  { key: 'concept', label: '概念' },
  { key: 'synthesis', label: '合成' },
  { key: 'meme', label: '梗' },
]

export const useMemoryStore = defineStore('memory', () => {
  const wikiPages = ref<WikiPageEntry[]>([])
  const selectedPath = ref<string | null>(null)
  const loading = ref(false)
  const filterType = ref<string | null>(null)
  const searchQuery = ref('')

  const filteredPages = computed(() => {
    let list = wikiPages.value

    if (filterType.value) {
      list = list.filter((m) => m.page_type === filterType.value)
    }

    if (searchQuery.value.trim()) {
      const q = searchQuery.value.toLowerCase()
      list = list.filter(
        (m) =>
          m.content.toLowerCase().includes(q) ||
          m.title.toLowerCase().includes(q),
      )
    }

    return list
  })

  async function fetchWikiPages(sessionId: string): Promise<void> {
    const socket = getSocket()
    console.log('[MemoryStore] fetchWikiPages called, socket:', !!socket, 'sessionId:', sessionId)
    if (!socket) return

    loading.value = true
    socket.emit(Events.MEMORY.LIST_PAGES, { session_id: sessionId }, (response: { pages: WikiPageEntry[] }) => {
      console.log('[MemoryStore] get_wiki_pages response:', response?.pages?.length, 'pages')
      wikiPages.value = response.pages ?? []
      loading.value = false
    })
  }

  function selectPath(path: string): void {
    selectedPath.value = selectedPath.value === path ? null : path
  }

  function setFilter(type: string | null): void {
    filterType.value = type
  }

  function setSearch(query: string): void {
    searchQuery.value = query
  }

  return {
    wikiPages,
    selectedPath,
    loading,
    filterType,
    searchQuery,
    filteredPages,
    fetchWikiPages,
    selectPath,
    setFilter,
    setSearch,
  }
})
