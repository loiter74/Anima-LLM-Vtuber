# Persona Training Lab Runtime Contract

Anima runtime consumes reviewed JSON exports from the independent `anima-training-lab`
project. Runtime code must not import training-lab Python modules and must not require
training dependencies such as `torch`, `transformers`, `peft`, or `accelerate`.

Allowed artifacts:

- `adapter_manifest.json`: base model, adapter path, dataset version, evaluation status,
  and safety boundary metadata.
- `runtime_style_pack.json`: prompt patch text, banned identity/source terms, style notes,
  and reviewed example pairs.

Runtime artifacts must not include raw private source text or unredacted copyrighted
dialogue. The training lab owns raw extraction, redaction, SFT building, LoRA training,
evaluation, and local validation reports.
