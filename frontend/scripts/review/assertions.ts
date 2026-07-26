import type { AssertionRecord } from './browser'

export async function recordAssertion(
  assertions: AssertionRecord[],
  name: string,
  assertion: () => Promise<void> | void,
): Promise<void> {
  try {
    await assertion()
    assertions.push({ name, passed: true })
  } catch (error) {
    assertions.push({
      name,
      passed: false,
      detail: error instanceof Error ? error.message : String(error),
    })
  }
}
