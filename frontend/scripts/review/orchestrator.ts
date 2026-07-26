import type { ReviewDefinition, ReviewScene } from '../../src/review/contracts'
import type { Decision } from './policies'

export interface ExecutedAttempt {
  technicalPassed: boolean
}

export interface WorkflowAttempt<Execution extends ExecutedAttempt = ExecutedAttempt> {
  sceneId: string
  attempt: number
  execution: Execution
  decision: Decision
}

export interface WorkflowResult<Execution extends ExecutedAttempt = ExecutedAttempt> {
  allPass: boolean
  attempts: readonly WorkflowAttempt<Execution>[]
}

export async function runReviewWorkflow<Action, Execution extends ExecutedAttempt>(_options: {
  definition: ReviewDefinition<string, Action>
  execute: (scene: ReviewScene<string, Action>, attempt: number) => Promise<Execution>
  decide: (technicalPassed: boolean) => Promise<Decision>
  persist: (attempt: WorkflowAttempt<Execution>) => Promise<void>
  interactive: boolean
}): Promise<WorkflowResult<Execution>> {
  const attempts: WorkflowAttempt<Execution>[] = []
  let allPass = true

  for (const scene of _options.definition.scenes) {
    let attemptNumber = 1
    let scenePassed = false
    for (;;) {
      const execution = await _options.execute(scene, attemptNumber)
      const decision = await _options.decide(execution.technicalPassed)
      const attempt = {
        sceneId: scene.id,
        attempt: attemptNumber,
        execution,
        decision,
      }
      await _options.persist(attempt)
      attempts.push(attempt)

      if (decision.outcome === 'passed') {
        scenePassed = true
        break
      }
      const repeatRequested =
        _options.interactive &&
        execution.technicalPassed &&
        (decision.humanVerdict === 'adjust' || decision.humanVerdict === 'redo')
      if (!repeatRequested) break
      attemptNumber += 1
    }
    if (!scenePassed) allPass = false
  }

  return { allPass, attempts }
}
