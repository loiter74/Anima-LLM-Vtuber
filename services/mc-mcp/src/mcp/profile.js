import path from 'node:path';


export const DEFAULT_CONNECT_TIMEOUT_MS = 60_000;
export const DEFAULT_SERVER_READINESS_TIMEOUT_MS = 45_000;


const SETUP_COMMAND = /^(gamerule [A-Za-z]+ (?:true|false)|time set \d+|forceload add -?\d+ -?\d+ -?\d+ -?\d+|clear [A-Za-z0-9_]{1,16}|give [A-Za-z0-9_]{1,16} minecraft:[a-z0-9_]+ \d+|fill -?\d+ -?\d+ -?\d+ -?\d+ -?\d+ -?\d+ minecraft:[a-z0-9_]+ replace|summon minecraft:(?:zombie|skeleton|spider) -?\d+ -?\d+ -?\d+ \{NoAI:1b,PersistenceRequired:1b\}|setblock -?\d+ -?\d+ -?\d+ minecraft:[a-z0-9_]+ replace|tp [A-Za-z0-9_]{1,16} -?\d+ -?\d+ -?\d+)$/;
const MINECRAFT_USERNAME = /^[A-Za-z0-9_]{1,16}$/;
const ENVIRONMENT_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
const PRESENTATION_MODES = new Set(['off', 'visual_only', 'full']);
const PRESENTATION_TEMPOS = new Set(['brisk', 'normal', 'calm']);


function isPositiveInteger(value, maximum = Number.MAX_SAFE_INTEGER) {
  return Number.isInteger(value) && value > 0 && value <= maximum;
}


function isRepositoryRelativeFile(value) {
  if (typeof value !== 'string' || value.trim() !== value || value.length === 0) return false;
  if (path.posix.isAbsolute(value) || path.win32.isAbsolute(value)) return false;
  return value.replaceAll('\\', '/').split('/').every((segment) => (
    segment.length > 0 && segment !== '.' && segment !== '..'
  ));
}


function validEnvironment(environment) {
  return environment === undefined || (
    environment !== null
    && typeof environment === 'object'
    && !Array.isArray(environment)
    && Object.entries(environment).every(([name, value]) => (
      ENVIRONMENT_NAME.test(name)
      && ['string', 'number', 'boolean'].includes(typeof value)
    ))
  );
}


export function isAllowedSetupCommand(commandText) {
  return typeof commandText === 'string'
    && commandText.length <= 512
    && SETUP_COMMAND.test(commandText);
}


export function validateProfile(profile) {
  if (!profile || typeof profile !== 'object' || Array.isArray(profile)) {
    throw new Error('INVALID_PROFILE');
  }
  if (!['managed', 'external'].includes(profile.mode)) throw new Error('INVALID_PROFILE_MODE');
  if (
    typeof profile.server?.host !== 'string'
    || profile.server.host.length === 0
    || !isPositiveInteger(profile.server?.port, 65_535)
  ) {
    throw new Error('INVALID_SERVER_PROFILE');
  }
  if (!MINECRAFT_USERNAME.test(profile.bot?.username ?? '')) {
    throw new Error('INVALID_BOT_PROFILE');
  }
  if (
    profile.connect_timeout_ms !== undefined
    && (
      !Number.isInteger(profile.connect_timeout_ms)
      || profile.connect_timeout_ms <= 0
      || profile.connect_timeout_ms > DEFAULT_CONNECT_TIMEOUT_MS
    )
  ) {
    throw new Error('INVALID_CONNECT_TIMEOUT');
  }
  if (
    profile.prepare_timeout_ms !== undefined
    && !isPositiveInteger(profile.prepare_timeout_ms)
  ) {
    throw new Error('INVALID_PREPARE_TIMEOUT');
  }
  if (
    profile.server.connect_readiness_timeout_ms !== undefined
    && !isPositiveInteger(
      profile.server.connect_readiness_timeout_ms,
      DEFAULT_CONNECT_TIMEOUT_MS,
    )
  ) {
    throw new Error('INVALID_SERVER_READINESS_TIMEOUT');
  }
  if (
    profile.bot.login_timeout_ms !== undefined
    && !isPositiveInteger(profile.bot.login_timeout_ms, DEFAULT_CONNECT_TIMEOUT_MS)
  ) {
    throw new Error('INVALID_BOT_LOGIN_TIMEOUT');
  }
  if (
    profile.bot.version !== undefined
    && (typeof profile.bot.version !== 'string' || profile.bot.version.length === 0)
  ) {
    throw new Error('INVALID_BOT_VERSION');
  }
  if (
    profile.bot.presentation !== undefined
    && (
      profile.bot.presentation === null
      || typeof profile.bot.presentation !== 'object'
      || Array.isArray(profile.bot.presentation)
      || Object.keys(profile.bot.presentation).some((key) => !['mode', 'tempo', 'seed'].includes(key))
      || (
        profile.bot.presentation.mode !== undefined
        && !PRESENTATION_MODES.has(profile.bot.presentation.mode)
      )
      || (
        profile.bot.presentation.tempo !== undefined
        && !PRESENTATION_TEMPOS.has(profile.bot.presentation.tempo)
      )
      || (
        profile.bot.presentation.seed !== undefined
        && (
          typeof profile.bot.presentation.seed !== 'string'
          || profile.bot.presentation.seed.trim().length < 1
          || profile.bot.presentation.seed.length > 128
        )
      )
    )
  ) {
    throw new Error('INVALID_BOT_PRESENTATION');
  }
  if (
    profile.mode === 'managed'
    && !isRepositoryRelativeFile(profile.server.compose_file)
  ) {
    throw new Error('INVALID_MANAGED_PROFILE');
  }
  if (!validEnvironment(profile.server.environment)) {
    throw new Error('INVALID_MANAGED_ENVIRONMENT');
  }
  if (
    profile.viewer !== undefined
    && (
      profile.viewer === null
      || typeof profile.viewer !== 'object'
      || Array.isArray(profile.viewer)
    )
  ) {
    throw new Error('INVALID_VIEWER_PROFILE');
  }
  if (
    profile.viewer?.username !== undefined
    && !MINECRAFT_USERNAME.test(profile.viewer.username)
  ) {
    throw new Error('INVALID_VIEWER_PROFILE');
  }
  if (
    (profile.viewer?.required !== undefined && typeof profile.viewer.required !== 'boolean')
    || (
      profile.viewer?.auto_attach !== undefined
      && typeof profile.viewer.auto_attach !== 'boolean'
    )
  ) {
    throw new Error('INVALID_VIEWER_PROFILE');
  }
  if (
    profile.viewer?.attach_timeout_ms !== undefined
    && !isPositiveInteger(profile.viewer.attach_timeout_ms, DEFAULT_CONNECT_TIMEOUT_MS)
  ) {
    throw new Error('INVALID_VIEWER_ATTACH_TIMEOUT');
  }
  for (const field of ['poll_interval_seconds', 'spectate_timeout_seconds']) {
    const value = profile.viewer?.[field];
    if (value !== undefined && (!Number.isFinite(value) || value <= 0)) {
      throw new Error('INVALID_VIEWER_PROFILE');
    }
  }
  if (profile.viewer?.required && (!profile.viewer.username || profile.viewer.auto_attach === false)) {
    throw new Error('INVALID_REQUIRED_VIEWER_PROFILE');
  }
  return profile;
}


export function validateConfig(config) {
  if (
    !config
    || typeof config !== 'object'
    || Array.isArray(config)
    || !config.profiles
    || typeof config.profiles !== 'object'
    || Array.isArray(config.profiles)
    || Object.keys(config.profiles).length === 0
  ) {
    throw new Error('INVALID_PROFILES');
  }
  for (const profile of Object.values(config.profiles)) validateProfile(profile);
  return config;
}


export function configuredProfile(config, profileName) {
  const profile = config.profiles?.[profileName];
  if (!profile) throw new Error(`UNKNOWN_PROFILE:${profileName}`);
  return validateProfile(profile);
}
