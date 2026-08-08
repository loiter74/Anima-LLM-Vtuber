# Minecraft manual integration scripts

Manual transport and observation diagnostics live here. Gameplay workflows are
not launched directly from scripts: submit typed requests through `mc_execute`,
inspect `mc_status`, and stop through `mc_stop`.

The former TechTreeRunner scripts were removed because they bypassed the durable
single-consumer control plane. Use `scripts/voyager_real_e2e.py` for the bounded
cross-runtime acceptance workflow.
