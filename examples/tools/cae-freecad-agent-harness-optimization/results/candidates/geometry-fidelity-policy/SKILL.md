---
name: geometry-fidelity-policy
description: Mandatory acceptance policy for source-referenced CAD reconstruction; separates geometric fidelity from structural and persistence checks.
---

# Geometry Fidelity Policy

Use this policy whenever the task provides source geometry, such as a mesh, scan,
point cloud, drawing, or reference model, and asks for a reconstruction or match.

## Independent acceptance concerns

Treat these as separate claims:

1. **Structural validity**: the candidate is a valid solid and has suitable topology,
   dimensions, and parametric structure.
2. **Persistence validity**: the saved artifact can be reopened and retains the
   intended editable structure.
3. **Geometric fidelity**: the candidate's surfaces actually resemble the supplied
   source geometry after an explicitly documented alignment.

Structural and persistence evidence cannot substitute for geometric-fidelity
evidence. Matching a bounding box or a few global dimensions is also not sufficient
fidelity evidence because materially different surfaces can share those properties.
Continue using the existing structural, parametric, and save/reopen checks; apply this
policy as an additional acceptance gate.

## Mandatory source-referenced fidelity gate

Before claiming success:

1. Identify the authoritative source geometry and the candidate geometry being
   compared. Record any unit conversion, coordinate transform, or registration used.
2. State an explicit fidelity tolerance in the model's units. Derive and justify it
   from the requested accuracy, source resolution/uncertainty, and feature scale;
   never leave the tolerance implicit or select it after seeing the result.
3. Produce **bidirectional** source-referenced evidence by using one of these
   symmetric comparisons:
   - **Surface distance:** sample the source and candidate surfaces, then report
     candidate-to-source and source-to-candidate distances separately (including a
     worst-case or justified high-percentile statistic) against the stated tolerance.

     **Bound the sampling hard.** Use at most **500 points per direction**, drawn
     by uniform or random subsampling of the mesh vertices. Never iterate over every
     vertex in Python, and never call `distToShape` inside a loop: both are
     quadratic in mesh size and will hang the application rather than finish
     slowly. Keep any single `execute_code` call under ~30 seconds of work; split
     measurement across calls instead of deepening one. If a measurement does not
     return, report fidelity as unverified; do not retry at higher density.
   - **Overlap:** compute a registered volumetric/surface overlap measure that
     penalizes both candidate material outside the source and source material missing
     from the candidate, and state the numerical acceptance threshold.
4. Preserve the measurements, threshold, alignment, and pass/fail result in the tool
   output or final verification report so the conclusion is auditable.

A one-way nearest-distance result is insufficient: it can hide missing source
features or unsupported extra candidate geometry. Visual inspection alone, screenshots,
solid validity, topology counts, global dimensions, parametric structure, and successful
save/reopen are supporting checks, not substitutes for the bidirectional comparison.

## Decision rule (mandatory)

Report the reconstruction as successful only when **all** required structural and
persistence checks pass **and** the independent fidelity gate above passes its stated
tolerance. If bidirectional evidence cannot be computed, is missing, or exceeds the
tolerance, explicitly report geometric fidelity as unverified or failed and do not
claim overall success.

### Refinement after a failed fidelity check (mandatory)

When the fidelity comparison fails, refine the model with a controlled,
evidence-linked loop:

1. Preserve a localized error map over the registered geometry, including both
directed errors, and mark every region that exceeds the predeclared tolerance.
2. For each high-error region, identify the candidate feature that controls that
region and the responsible parameter or parameter family. Record the
error-to-feature-to-parameter link before editing; do not make an unexplained
global extent change.
3. In one iteration, adjust only one parameter family (a set of parameters that
jointly controls the same geometric feature). Hold all unrelated parameter
families fixed so the effect of the adjustment remains attributable.
4. Rerun the same registered, bidirectional comparison, regenerate the localized
error map, and remeasure against the **unchanged predeclared tolerance**. Accept
the iteration only if the targeted high-error region improves without creating
or worsening another out-of-tolerance region. Otherwise revert or revise that
same parameter family before selecting a different family.

Repeat this loop until no mapped region exceeds the original tolerance. Never
relax or replace the tolerance during refinement, and do not claim acceptance
from visual improvement or global dimensions alone.

### Correct versus incorrect application

- **Correct:** report the alignment, predeclared tolerance, both directed surface
  error results (or a symmetric overlap result), and an independent fidelity verdict,
  alongside the existing solid and save/reopen checks.
- **Incorrect:** conclude that the reconstruction matches the source because it is a
  valid solid, has plausible dimensions, and reopens successfully, without a measured
  source-referenced comparison.
