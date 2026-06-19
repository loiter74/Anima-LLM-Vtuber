/**
 * Plan Executor - executes multi-step plans from Python planner
 * 
 * Supports two modes:
 * - planner: autonomous plan execution with state transitions
 * - rule: passive, waits for Python commands (existing behavior)
 */

// ── Mode management ──
let currentMode = 'rule';     // 'planner' | 'rule'
let plan = [];               // Current plan steps
let planStep = 0;            // Current step index
let planStepStatus = {};     // Per-step status tracking
let onPlanComplete = null;   // Callback when plan finishes

export function getMode() { return currentMode; }
export function getPlanProgress() {
    return { step: planStep, total: plan.length, status: planStepStatus, mode: currentMode };
}

/**
 * Set bot to planner mode and start executing a plan
 * @param {Array} planSteps - Array of {action, params} objects
 */
export function setPlannerMode(planSteps) {
    plan = planSteps;
    planStep = 0;
    planStepStatus = {};
    currentMode = 'planner';
    return { status: 'planner_started', steps: plan.length };
}

/**
 * Set bot to rule mode (Python sends individual commands)
 */
export function setRuleMode() {
    currentMode = 'rule';
    plan = [];
    planStep = 0;
    if (stateMachine) {
        try { stateMachine.stop(); } catch(e) {}
        stateMachine = null;
    }
    return { status: 'rule_mode' };
}

/**
 * Get the next plan step, or null if plan is complete
 */
export function nextPlanStep() {
    if (planStep >= plan.length) return null;
    const step = plan[planStep];
    planStep++;
    return step;
}

/**
 * Mark current step as failed and request replan
 */
export function stepFailed(error) {
    planStepStatus[planStep - 1] = { status: 'failed', error };
    return { 
        need_replan: true, 
        failed_at: planStep - 1, 
        remaining: plan.length - (planStep - 1) 
    };
}

/**
 * Mark current step as complete
 */
export function stepComplete(result) {
    planStepStatus[planStep - 1] = { status: 'completed', ...result };
    if (planStep >= plan.length && onPlanComplete) {
        onPlanComplete({ status: 'plan_complete', steps: plan.length });
    }
}

export function setOnPlanComplete(cb) { onPlanComplete = cb; }
