# Bounded execution feedback

Animetta's five-minute guarantee is a **feedback deadline**, not a promise that a complete plan finishes in five minutes. Every execution window reserves up to 240 seconds for action, 30 seconds for evidence, and 30 seconds for cleanup and result publication. A long logical step may therefore return `in_progress` with a durable checkpoint or an exact owned-resource lease and continue in another window.

A plan is successful only when every required DAG step has a valid passing result. `in_progress`, blocked, timed-out, cancelled, missing, or evidence-invalid required steps can never be aggregated as success. Valid upstream and unrelated checkpoints are reused; changed inputs invalidate only the affected step and its transitive downstream dependants.

## Operator commands

Inspect the latest result for every step:

```powershell
py -3.13 -m tooling.execution_feedback --root artifacts/iteration-plans inspect --run-id <run-id>
```

Queue continuation of a nonterminal step:

```powershell
py -3.13 -m tooling.execution_feedback --root artifacts/iteration-plans continue --run-id <run-id> --step-id <step-id>
```

Cancel only the exact resource named by an owned lease:

```powershell
py -3.13 -m tooling.execution_feedback --root artifacts/iteration-plans cancel --lease-id <lease-id>
```

Display a fifth-failure reflection:

```powershell
py -3.13 -m tooling.execution_feedback --root artifacts/iteration-plans reflection --fingerprint <sha256>
```

Cancellation revalidates the PID/container ID and its creation token before acting. Name-based, port-based, broad project, or pattern-based cleanup is forbidden. Protected external resources—including an existing Minecraft client, Minecraft server, host Qwen process, and unrelated user processes—are observation-only and must never be stopped, restarted, recreated, attached to, or otherwise controlled by the bounded execution system unless the current plan owns their exact creation token.

Lifecycle, impact-aware quality, R7, and R8 entrypoints use bounded feedback by default. Retain the printed run ID for resumption; there is no monolithic silent-wait switch.
