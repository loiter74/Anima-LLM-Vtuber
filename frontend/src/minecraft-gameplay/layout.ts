export interface BroadcastRect {
  readonly x: number
  readonly y: number
  readonly width: number
  readonly height: number
}

export interface MinecraftGameplayLayout {
  readonly canvas: Pick<BroadcastRect, 'width' | 'height'>
  readonly television: BroadcastRect
  readonly aperture: BroadcastRect
  readonly danmaku: BroadcastRect
  readonly subtitle: BroadcastRect
  readonly avatar: BroadcastRect
}

export type MinecraftGameplayMode = 'preview' | 'overlay'

export const MINECRAFT_GAMEPLAY_LAYOUT: MinecraftGameplayLayout = {
  canvas: { width: 1920, height: 1080 },
  television: { x: 184, y: 76, width: 1552, height: 921 },
  aperture: { x: 216, y: 112, width: 1488, height: 837 },
  danmaku: { x: 246, y: 142, width: 400, height: 244 },
  subtitle: { x: 400, y: 964, width: 1120, height: 72 },
  avatar: { x: 1460, y: 388, width: 460, height: 692 },
}

export function resolveMinecraftGameplayMode(search: URLSearchParams): MinecraftGameplayMode {
  return search.get('overlay') === '1' ? 'overlay' : 'preview'
}

export function toCssVariables(layout: MinecraftGameplayLayout): Record<string, string> {
  return {
    '--broadcast-width': `${layout.canvas.width}px`,
    '--broadcast-height': `${layout.canvas.height}px`,
    '--television-x': `${layout.television.x}px`,
    '--television-y': `${layout.television.y}px`,
    '--television-width': `${layout.television.width}px`,
    '--television-height': `${layout.television.height}px`,
    '--screen-x': `${layout.aperture.x}px`,
    '--screen-y': `${layout.aperture.y}px`,
    '--screen-width': `${layout.aperture.width}px`,
    '--screen-height': `${layout.aperture.height}px`,
    '--danmaku-x': `${layout.danmaku.x}px`,
    '--danmaku-y': `${layout.danmaku.y}px`,
    '--danmaku-width': `${layout.danmaku.width}px`,
    '--danmaku-height': `${layout.danmaku.height}px`,
    '--subtitle-x': `${layout.subtitle.x}px`,
    '--subtitle-y': `${layout.subtitle.y}px`,
    '--subtitle-width': `${layout.subtitle.width}px`,
    '--subtitle-height': `${layout.subtitle.height}px`,
    '--avatar-x': `${layout.avatar.x}px`,
    '--avatar-y': `${layout.avatar.y}px`,
    '--avatar-width': `${layout.avatar.width}px`,
    '--avatar-height': `${layout.avatar.height}px`,
  }
}
