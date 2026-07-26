export interface ImageRegion {
  x: number
  y: number
  width: number
  height: number
}

export interface ImageComparison {
  mismatchRatio: number
  passed: boolean
}

export function comparePngRegion(
  _expectedCrop: Buffer,
  _actualFullImage: Buffer,
  _region: ImageRegion,
  _maximumMismatchRatio = 0.1,
): ImageComparison {
  const expected = PNG.sync.read(_expectedCrop)
  const actual = PNG.sync.read(_actualFullImage)
  const region = {
    x: Math.floor(_region.x),
    y: Math.floor(_region.y),
    width: Math.ceil(_region.x + _region.width) - Math.floor(_region.x),
    height: Math.ceil(_region.y + _region.height) - Math.floor(_region.y),
  }
  if (
    region.x < 0 ||
    region.y < 0 ||
    region.width < 1 ||
    region.height < 1 ||
    region.x + region.width > actual.width ||
    region.y + region.height > actual.height
  ) {
    throw new Error('Image comparison region is outside the OBS screenshot')
  }
  if (expected.width !== region.width || expected.height !== region.height) {
    throw new Error('Chrome crop dimensions do not match the comparison region')
  }

  const actualCrop = new PNG({ width: region.width, height: region.height })
  for (let y = 0; y < region.height; y += 1) {
    const sourceStart = ((region.y + y) * actual.width + region.x) * 4
    const sourceEnd = sourceStart + region.width * 4
    actual.data.copy(actualCrop.data, y * region.width * 4, sourceStart, sourceEnd)
  }
  const mismatchedPixels = pixelmatch(
    expected.data,
    actualCrop.data,
    undefined,
    region.width,
    region.height,
    { threshold: 0.2, includeAA: false },
  )
  const mismatchRatio = mismatchedPixels / (region.width * region.height)
  return {
    mismatchRatio,
    passed: mismatchRatio <= _maximumMismatchRatio,
  }
}
import pixelmatch from 'pixelmatch'
import { PNG } from 'pngjs'
