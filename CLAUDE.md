# h4nb

h4nb is a CUDA direct N-body library (Hermite 4, block time steps, FP64, multi-GPU). Read these files first:

- `.specify/memory/constitution.md`: the project rules. They have priority.
- `docs/cuda-best-practices.md`: **read this file before you write or change code.** It gives rules for kernels, numerics, error handling, C++ pitfalls and verification.
- `specs/001-hermite-nbody-lib/spec.md` and `quickstart.md`: the requirements and the acceptance runs.
- `docs/superpowers/plans/2026-11-07-h4nb.md`: the implementation plan and design decisions D1 to D11.

Rules for sessions:

- **Write all documentation and all text files in Simplified Technical English (ASD-STE100).** Use short sentences. Use active voice. Give one instruction in each sentence. Use one word for one meaning. Code, identifiers and quoted output stay unchanged.
- Do not commit or push unless the user asks.
- The Mac cannot run CUDA. Build in the container (see the plan). State what you only compiled and what you ran.
- Several sessions work in this repository. Send a message to the other session before you edit a file that it edits.
