/**
 * Shared State Stores
 * 中央导出点 - 只保留真正跨 feature 的 store
 *
 * 注意：大部分 store 已移至各个 feature 目录
 * - Connection Store → @/features/connection/stores/connectionStore
 * - Conversation Store → @/features/conversation/stores/conversationStore
 * - Audio Store → 保留在此（跨 feature 使用）
 */

export { useAudioStore } from './audioStore'
