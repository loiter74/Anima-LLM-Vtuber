// survival/report.js — Report and phase-result builders for survival iron runner.

/**
 * Create a fresh phase result object.
 * @param {string} phase
 * @returns {object}
 */
export function createPhaseResult(phase) {
  return {
    phase,
    success: true,
    actions_attempted: 0,
    actions_succeeded: 0,
    failure_category: null,
    failure_message: '',
  };
}

/**
 * Record an action attempt on a phase result.
 * @param {object} phaseResult
 * @param {boolean} success
 */
export function recordAction(phaseResult, success) {
  phaseResult.actions_attempted += 1;
  if (success) {
    phaseResult.actions_succeeded += 1;
  }
}

/**
 * Mark a phase result as failed.
 * @param {object} phaseResult
 * @param {string} category
 * @param {string} message
 */
export function markFailure(phaseResult, category, message) {
  phaseResult.success = false;
  phaseResult.failure_category = category;
  phaseResult.failure_message = message;
}

/**
 * Create a fresh run report.
 * @returns {object}
 */
export function createReport() {
  return {
    completed: false,
    elapsed_seconds: 0,
    deaths: 0,
    phase_results: [],
    final_inventory: {},
    iron_gear_achieved: {},
  };
}

/**
 * Finalize a report with elapsed time and inventory.
 * @param {object} report
 * @param {number} startTime - Date.now() at run start
 * @param {Object<string, number>} finalInventory
 * @param {Object<string, boolean>} ironGearAchieved
 */
export function finalizeReport(report, startTime, finalInventory, ironGearAchieved) {
  report.elapsed_seconds = Math.round((Date.now() - startTime) / 1000 * 10) / 10;
  report.final_inventory = finalInventory;
  report.iron_gear_achieved = ironGearAchieved;
}
