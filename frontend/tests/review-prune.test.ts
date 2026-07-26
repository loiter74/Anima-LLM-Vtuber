import { mkdtemp, mkdir, readFile, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { applyReviewPrune, planReviewPrune } from '../scripts/review/prune'

async function createRun(root: string, runId: string, status: string): Promise<void> {
  const directory = join(root, runId)
  await mkdir(directory)
  await writeFile(join(directory, 'summary.json'), JSON.stringify({ status }))
  await writeFile(join(directory, 'evidence.txt'), 'evidence')
}

describe('review artifact pruning', () => {
  it('dry-runs status and superseded-passed candidates while honoring repeated keep rules', async () => {
    const root = await mkdtemp(join(tmpdir(), 'animetta-review-prune-'))
    const failed = '2026-07-01T00-00-00Z-failed1'
    const passed = '2026-07-02T00-00-00Z-passed1'
    const kept = '2026-07-03T00-00-00Z-kept1'
    await createRun(root, failed, 'failed')
    await createRun(root, passed, 'passed')
    await createRun(root, kept, 'passed')

    const plan = await planReviewPrune({
      root,
      keepRuns: [kept],
      deleteSupersededPassed: true,
    })

    expect(plan.candidates.map(({ runId }) => runId)).toEqual([failed, passed])
    expect(plan.kept).toEqual([{ runId: kept, reason: 'keep-run' }])
    expect(await readFile(join(root, failed, 'evidence.txt'), 'utf8')).toBe('evidence')
  })

  it('applies a frozen plan idempotently', async () => {
    const root = await mkdtemp(join(tmpdir(), 'animetta-review-prune-'))
    const failed = '2026-07-01T00-00-00Z-failed1'
    await createRun(root, failed, 'failed')
    const plan = await planReviewPrune({ root })

    await applyReviewPrune(plan)
    await applyReviewPrune(plan)

    expect((await planReviewPrune({ root })).candidates).toEqual([])
  })

  it('rejects malformed keep identifiers before selecting any target', async () => {
    const root = await mkdtemp(join(tmpdir(), 'animetta-review-prune-'))
    await expect(planReviewPrune({ root, keepRuns: ['..'] })).rejects.toThrow(
      'Invalid review run identifier',
    )
  })

  it('rejects a linked run directory before selecting deletion targets', async () => {
    const root = await mkdtemp(join(tmpdir(), 'animetta-review-prune-'))
    const outside = await mkdtemp(join(tmpdir(), 'animetta-review-outside-'))
    await symlink(outside, join(root, '2026-07-01T00-00-00Z-linked1'), 'junction')

    await expect(planReviewPrune({ root })).rejects.toThrow('Review run is a link')
  })
})
