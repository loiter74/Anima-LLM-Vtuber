export type Live2DAction =
  | { type: 'expression'; name: string }
  | { type: 'motion'; group: string; index: number }
  | { type: 'param'; name: string; value: number }
  | { type: 'sequence'; actions: Live2DAction[] }
  | { type: 'wait'; ms: number }
