/**
 * Conversation Status Constants
 * Provides styling and labels for different conversation statuses
 */

import type { ConversationStatus } from "../types/conversation"

export interface StatusStyle {
  label: string
  bg: string
  text: string
}

export const STATUS_STYLES: Record<ConversationStatus, StatusStyle> = {
  idle: {
    label: "空闲",
    bg: "bg-gray-500/10",
    text: "text-gray-500",
  },
  listening: {
    label: "监听中",
    bg: "bg-red-500/10",
    text: "text-red-500",
  },
  processing: {
    label: "处理中",
    bg: "bg-yellow-500/10",
    text: "text-yellow-500",
  },
  speaking: {
    label: "说话中",
    bg: "bg-blue-500/10",
    text: "text-blue-500",
  },
  interrupted: {
    label: "已打断",
    bg: "bg-orange-500/10",
    text: "text-orange-500",
  },
  error: {
    label: "错误",
    bg: "bg-red-500/10",
    text: "text-red-500",
  },
}

export const DEFAULT_SERVER_URL = "http://localhost:12394"
export const DEFAULT_SAMPLE_RATE = 16000
