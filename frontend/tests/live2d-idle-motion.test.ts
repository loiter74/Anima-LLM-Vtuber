// @vitest-environment node

import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

interface Point {
  time: number
  value: number
}

interface Segment {
  kind: number
  start: Point
  control1?: Point
  control2?: Point
  end: Point
}

interface MotionCurve {
  Id: string
  Segments: number[]
}

interface MotionFile {
  Meta: { Duration: number }
  Curves: MotionCurve[]
}

function decodeSegments(values: readonly number[]): Segment[] {
  const segments: Segment[] = []
  let start = { time: values[0], value: values[1] }
  let index = 2
  while (index < values.length) {
    const kind = values[index++]
    if (kind === 1) {
      const control1 = { time: values[index], value: values[index + 1] }
      const control2 = { time: values[index + 2], value: values[index + 3] }
      const end = { time: values[index + 4], value: values[index + 5] }
      segments.push({ kind, start, control1, control2, end })
      start = end
      index += 6
      continue
    }
    const end = { time: values[index], value: values[index + 1] }
    segments.push({ kind, start, end })
    start = end
    index += 2
  }
  return segments
}

function startSlope(segment: Segment): number {
  const next = segment.control1 ?? segment.end
  return (next.value - segment.start.value) / (next.time - segment.start.time)
}

function endSlope(segment: Segment, duration: number): number {
  if (segment.end.time < duration) return 0
  const previous = segment.control2 ?? segment.start
  return (segment.end.value - previous.value) / (segment.end.time - previous.time)
}

describe('Mao idle motion assets', () => {
  it.each(['mtn_01.motion3.json', 'sample_01.motion3.json'])(
    'closes %s with continuous value and velocity',
    async (fileName) => {
      const path = resolve('public/live2d/mao/motions', fileName)
      const motion = JSON.parse(await readFile(path, 'utf8')) as MotionFile

      expect(motion.Meta.Duration).toBe(5.6)
      for (const curve of motion.Curves) {
        const segments = decodeSegments(curve.Segments)
        const first = segments[0]
        const last = segments.at(-1)!
        expect(last.end.value, `${curve.Id} value seam`).toBeCloseTo(first.start.value, 5)
        expect(endSlope(last, motion.Meta.Duration), `${curve.Id} velocity seam`).toBeCloseTo(
          startSlope(first),
          1,
        )
      }
    },
  )
})
