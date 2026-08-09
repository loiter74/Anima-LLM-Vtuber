export interface Live2DLayoutInput {
  screenWidth: number
  screenHeight: number
  baseWidth: number
  baseHeight: number
}

export interface Live2DLayout {
  scale: number
  x: number
  y: number
}

const REVIEW_MODEL_SCALE = 1.5
const DANMAKU_PANEL_TOP_PX = 28

export function applyLiveReviewLayout(root: HTMLElement): void {
  root.style.removeProperty('--live-danmaku-panel-bottom')
  root.style.setProperty('--live-danmaku-panel-top', `${DANMAKU_PANEL_TOP_PX}px`)
}

export function computeLive2DLayout({
  screenWidth,
  screenHeight,
  baseWidth,
  baseHeight,
}: Live2DLayoutInput): Live2DLayout {
  const fittedScale = Math.min((screenWidth * 0.88) / baseWidth, (screenHeight * 0.82) / baseHeight)
  return {
    scale: fittedScale * REVIEW_MODEL_SCALE,
    x: screenWidth * 0.5,
    y: screenHeight * 0.8,
  }
}
