export type PipelineStage =
  | 'idle'
  | 'downloading'
  | 'separating'
  | 'transcribing'
  | 'waiting_lyrics'
  | 'converting'
  | 'mixing'
  | 'done'
  | 'error'

export interface LyricLine {
  text: string
  translation: string
  start_ms: number
  end_ms: number
}

export interface SongResult {
  task_id?: string
  audio_url: string
  subtitle_url: string
  tts_audio_url: string
  vocals_url: string
  original_url: string
  video_title: string
  duration: number
  lyrics: LyricLine[]
  volumes?: number[]
  voice_conversion_applied?: boolean
  voice_provider?: string
  voice_model?: string
  voice_revision?: string
  voice_name?: string
}
