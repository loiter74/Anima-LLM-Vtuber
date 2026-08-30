import type { LivestreamNarrationStateEvent } from '@/shared/contracts/socket-events'
import type { PublicActivityItem, PublicActivityView } from './publicActivity'

export interface DomPublicActivityViewOptions {
  panelId?: string
  listId?: string
  narrationId?: string
  currentIntentId?: string
  recentObservationId?: string
  nextPhaseId?: string
}

const INTENT_LABELS: Readonly<Record<string, string>> = {
  acquire: '收集',
  craft: '制作',
  build: '搭建',
  travel: '前往',
  combat: '应对',
  survive: '确保安全',
  learn: '学习',
  discover: '探索',
  interact: '处理',
}

const NEXT_PHASE_LABELS: Readonly<Record<string, string>> = {
  planning: '观察环境',
  observing: '确认行动',
  committed: '开始执行',
  acting: '检查结果',
  checking: '确认结果',
  recovering: '重新检查',
  finished: '等待新任务',
}

function requiredElement<T extends HTMLElement>(document: Document, id: string): T {
  const element = document.getElementById(id)
  if (!element) throw new Error(`Missing public activity element: ${id}`)
  return element as T
}

function speechStateLabel(state: string): string {
  const labels: Readonly<Record<string, string>> = {
    none: '仅展示',
    visual_only: '视觉提示',
    queued: '等待发言',
    speaking: '正在讲述',
    completed: '讲述完成',
    cancelled: '讲述取消',
    dropped: '仅保留状态',
    muted: '静音展示',
  }
  return labels[state] ?? state.replaceAll('_', ' ').replaceAll('-', ' ')
}

export function createDomPublicActivityView(
  document: Document,
  options: DomPublicActivityViewOptions = {},
): PublicActivityView {
  const panel = requiredElement<HTMLElement>(document, options.panelId ?? 'publicActivityPanel')
  const list = requiredElement<HTMLOListElement>(document, options.listId ?? 'publicActivityList')
  const narrationElement = requiredElement<HTMLElement>(
    document,
    options.narrationId ?? 'publicNarrationState',
  )
  const currentIntent = requiredElement<HTMLElement>(
    document,
    options.currentIntentId ?? 'publicCurrentIntent',
  )
  const recentObservation = requiredElement<HTMLElement>(
    document,
    options.recentObservationId ?? 'publicRecentObservation',
  )
  const nextPhase = requiredElement<HTMLElement>(document, options.nextPhaseId ?? 'publicNextPhase')
  let hasActivities = false
  let hasNarration = false

  const updatePanelVisibility = (): void => {
    panel.hidden = !hasActivities && !hasNarration
  }

  const activityElement = (): HTMLLIElement => {
    const item = document.createElement('li')
    item.className = 'public-activity-item'
    const phase = document.createElement('span')
    phase.className = 'public-activity-phase'
    const copy = document.createElement('p')
    copy.className = 'public-activity-copy'
    item.append(phase, copy)
    return item
  }

  return {
    renderPublicActivities(activities: readonly PublicActivityItem[]): void {
      const retainedIds = new Set(activities.map((activity) => activity.event_id))
      for (const child of [...list.children]) {
        if (!(child instanceof HTMLElement) || !retainedIds.has(child.dataset.eventId ?? '')) {
          child.remove()
        }
      }
      const byId = new Map(
        [...list.children]
          .filter((child): child is HTMLLIElement => child instanceof HTMLLIElement)
          .map((child) => [child.dataset.eventId ?? '', child]),
      )
      for (const activity of activities) {
        const item = byId.get(activity.event_id) ?? activityElement()
        item.dataset.eventId = activity.event_id
        item.dataset.phase = activity.payload.phase
        item.dataset.projectionVersion = String(activity.projection_version)
        item.dataset.outcome = activity.payload.outcome ?? 'active'
        const phase = item.querySelector<HTMLElement>('.public-activity-phase')
        const copy = item.querySelector<HTMLElement>('.public-activity-copy')
        if (phase) phase.textContent = activity.phaseLabel
        if (copy) copy.textContent = activity.visualText
        list.append(item)
      }
      const latest = activities.at(-1)
      const latestIntent = [...activities].reverse().find((activity) => activity.payload.intent)
      const observation = [...activities]
        .reverse()
        .find((activity) => activity.payload.phase === 'observing')
      currentIntent.textContent = latestIntent?.payload.intent
        ? [INTENT_LABELS[latestIntent.payload.intent], latestIntent.payload.focus?.label]
            .filter(Boolean)
            .join(' · ')
        : '等待任务'
      recentObservation.textContent = observation?.payload.focus?.label ?? '尚无观察'
      nextPhase.textContent = latest ? NEXT_PHASE_LABELS[latest.payload.phase] : '等待计划'
      const summarySources = [
        [currentIntent, latestIntent],
        [recentObservation, observation],
        [nextPhase, latest],
      ] as const
      for (const [element, source] of summarySources) {
        if (source) element.dataset.sourceEventId = source.event_id
        else delete element.dataset.sourceEventId
      }
      hasActivities = activities.length > 0
      updatePanelVisibility()
    },
    setPublicNarration(narration: LivestreamNarrationStateEvent | null): void {
      narrationElement.replaceChildren()
      hasNarration = narration !== null
      narrationElement.hidden = narration === null
      if (!narration) {
        for (const key of Object.keys(narrationElement.dataset)) {
          delete narrationElement.dataset[key]
        }
        updatePanelVisibility()
        return
      }
      narrationElement.dataset.cueId = narration.cue_id
      narrationElement.dataset.sourceEventId = narration.source_event_id
      narrationElement.dataset.phase = narration.phase
      narrationElement.dataset.speechState = narration.speech_state
      if (narration.task_id) narrationElement.dataset.taskId = narration.task_id
      else delete narrationElement.dataset.taskId
      const state = document.createElement('span')
      state.className = 'public-narration-state-label'
      state.textContent = speechStateLabel(narration.speech_state)
      const copy = document.createElement('p')
      copy.className = 'public-narration-copy'
      copy.textContent = narration.visual_text
      narrationElement.append(state, copy)
      updatePanelVisibility()
    },
  }
}
