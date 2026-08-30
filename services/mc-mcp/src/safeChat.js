/** Reject server commands on survival action surfaces. */
export function assertSurvivalChat(message) {
  const normalized = String(message ?? '');
  if (normalized.trimStart().startsWith('/')) {
    const error = new Error('Survival chat cannot send administrator commands');
    error.code = 'ADMIN_COMMAND_FORBIDDEN';
    error.retryable = false;
    throw error;
  }
  return normalized;
}
