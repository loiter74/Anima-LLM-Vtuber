/**
 * Conversation Types
 * 会话功能的数据模型类型
 *
 * 注意：Hook 配置类型（ConversationOptions）在 hooks/types.ts 中
 */

/**
 * 会话状态枚举
 */
export type ConversationStatus =
  | "idle"           // 空闲
  | "listening"      // 正在监听用户输入
  | "processing"     // 正在处理
  | "speaking"       // AI 正在说话
  | "interrupted"    // 被打断
  | "error"          // 错误

/**
 * 消息数据模型
 */
export interface Message {
  id: string
  sender: "user" | "ai"
  text: string
  time: string
  status?: "pending" | "sent" | "error"
}
