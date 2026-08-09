export interface ReviewCliOptions {
  featureId: string
  baseUrl: string
  interactive: boolean
  headed: boolean
  requireObs: boolean
  obsUrl: string
  obsSceneName: string
  obsSourceName: string
  printUrl: boolean
  verdict: string | null
}

export function parseReviewOptions(
  _args: readonly string[],
  _environment: Readonly<Record<string, string | undefined>> = process.env,
): ReviewCliOptions {
  const options: ReviewCliOptions = {
    featureId: 'live',
    baseUrl: 'http://127.0.0.1:3000',
    interactive: false,
    headed: true,
    requireObs: true,
    obsUrl: _environment.OBS_WEBSOCKET_URL ?? 'ws://127.0.0.1:4455',
    obsSceneName: _environment.OBS_SCENE_NAME ?? 'Animetta Review',
    obsSourceName: _environment.OBS_SOURCE_NAME ?? 'Animetta Live Browser',
    printUrl: false,
    verdict: null,
  }
  const valueFlags: Record<string, keyof ReviewCliOptions> = {
    '--feature': 'featureId',
    '--base-url': 'baseUrl',
    '--obs-url': 'obsUrl',
    '--obs-scene': 'obsSceneName',
    '--obs-source': 'obsSourceName',
    '--verdict': 'verdict',
  }

  for (let index = 0; index < _args.length; index += 1) {
    const argument = _args[index]
    if (argument === '--') continue
    if (argument === '--interactive') {
      options.interactive = true
      options.headed = true
      continue
    }
    if (argument === '--headed') {
      options.headed = true
      continue
    }
    if (argument === '--headless') {
      options.headed = false
      continue
    }
    if (argument === '--no-obs') {
      options.requireObs = false
      continue
    }
    if (argument === '--print-url') {
      options.printUrl = true
      continue
    }
    const key = valueFlags[argument]
    if (key) {
      const value = _args[index + 1]
      if (!value || value.startsWith('--')) throw new Error(`${argument} requires a value`)
      options[key] = value as never
      index += 1
      continue
    }
    throw new Error(`Unknown option: ${argument}`)
  }
  if (options.verdict && !options.interactive) {
    throw new Error('--verdict requires --interactive')
  }
  return options
}
