export interface ReviewClock {
  setTimeout(callback: () => void, delayMs: number): number
  clearTimeout(id: number): void
}

export interface ScheduledAction<Action> {
  atMs: number
  action: Action
}

export interface ReviewScene<Id extends string, Action> {
  id: Id
  title: string
  observe: string
  readyTexts: readonly string[]
  timeline: readonly ScheduledAction<Action>[]
}

export interface ReviewDefinition<Id extends string, Action> {
  id: string
  contractVersion: number
  route: string
  viewport: Readonly<{ width: number; height: number }>
  scenes: readonly ReviewScene<Id, Action>[]
}

export interface ReviewSession {
  start(): void
  dispose(): void
}

export interface ReviewPlugin<Definition extends ReviewDefinition<string, unknown>> {
  definition: Definition
}
