import type { AttemptOutcome, DecisionSource } from './evidence'

export interface Decision {
  outcome: AttemptOutcome
  decisionSource: DecisionSource
  humanVerdict?: 'pass' | 'adjust' | 'redo'
  humanNote?: string
}

export function automaticDecision(_technicalPassed: boolean): Decision {
  return {
    outcome: _technicalPassed ? 'passed' : 'failed',
    decisionSource: 'automatic',
  }
}

export async function interactiveDecision(
  _technicalPassed: boolean,
  _prompt: () => Promise<{ verdict: 'pass' | 'adjust' | 'redo'; humanNote: string }>,
): Promise<Decision> {
  if (!_technicalPassed) return automaticDecision(false)
  const result = await _prompt()
  return {
    outcome: result.verdict === 'pass' ? 'passed' : 'failed',
    decisionSource: 'human',
    humanVerdict: result.verdict,
    humanNote: result.humanNote,
  }
}
