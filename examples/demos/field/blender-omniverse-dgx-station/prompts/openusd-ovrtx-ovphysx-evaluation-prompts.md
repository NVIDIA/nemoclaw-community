# OpenUSD, OVRTX, and OVPhysX workflow prompts

These prompts are written to be usable with any capable agent or model that has access to the required scene tools and libraries.

## 1. Process a scene into a metadata-ready OpenUSD handoff

```text
Process the active scene into a metadata-ready OpenUSD handoff while preserving the source scene and source USD layers.

Inspect the scene first and inventory every exportable object, material, collection, hierarchy relationship, camera, light, unit setting, up-axis assumption, external dependency, and existing physics property. Export the scene to a task-owned USD file and record the source and exported-file SHA-256 hashes.

Open the composed USD stage and resolve exact prim paths. Sort exported object paths deterministically and assign object_001, object_002, and so on. Create semantic_overlay.usda as a stronger editable layer containing sparse over specs and semantic label opinions. Preserve defaultPrim and use portable relative asset paths. Do not flatten, rename, reparent, deactivate, or copy unrelated source opinions.

Query every exact USD Material prim. Create simready_overlay.usda as a stronger non-destructive layer containing the nonvisual material metadata supported by the installed runtime. Classify materials only when explicit name-based rules match. Assign the valid none or unknown base to unmatched materials and mark them review_required=true instead of guessing. Write material_metadata.csv with the material prim path, source material name, selected nonvisual base, matched rule, and review status.

Package the source USD, both overlays, and all resolver-visible dependencies into a dependency-closed openusd_handoff_package.usdz. Generate openusd_handoff_manifest.json containing relative paths, file roles, SHA-256 hashes, source and composed stage metadata, semantic assignments, material counts, software versions, and dependency inventory.

Reopen and validate the package in a clean resolver context. Confirm valid composition, exact and unique semantic target paths, unique semantic IDs, valid material schema fields, dependency closure, preserved defaultPrim, unchanged source hashes, correct up axis, and correct metersPerUnit.

Return the USD, both overlays, material CSV, USDZ package, manifest, and a validation report. Summarize object count, material count, review-required count, elapsed time, software versions, validation errors, and all physics-readiness gaps. Metadata-ready does not mean physics-ready. Do not claim simulation readiness unless the scene also validates its physics scene, colliders, rigid bodies or articulations, joints, mass properties, units, up axis, and dependencies.
```

## 2. Render an OVRTX semantic overlay with 2D boxes

```text
Render semantic segmentation for [SEMANTIC_OVERLAY_USDA] using the installed OVRTX runtime.

Before rendering, verify that the runtime supports the required semantic output, stage-query, camera, and render-output capabilities. Inspect the composed stage, preserve its up axis and metersPerUnit, resolve the semantic labels to exact prim paths, and report any invalid or duplicate semantic assignments.

Render at 1024x576 after two warm-up frames. Capture the semantic-ID or SemanticSegmentation buffer and normalize it to a top-left pixel origin. Save the raw semantic-ID data when the runtime supports it.

Create semantic_label_map.json containing each renderer semantic ID, authored semantic label, exact prim path, display name, and stable display color. Generate semantic_mask.png from the captured semantic-ID buffer.

Compute every visible object's 2D bounding box directly from the pixels belonging to that renderer semantic ID in the same captured frame. Do not calculate boxes from a beauty render, a second frame, projected object bounds, or newly authored scene geometry. Write semantic_bounding_boxes.json with the semantic ID, label, prim path, pixel bounds, image dimensions, visible-pixel count, and normalized bounds.

Create semantic_bounding_boxes.png by combining the colorized semantic mask, 2D boxes, and readable text labels. Verify that every box and label maps to an ID present in the captured buffer and that the mask, label map, boxes, and labeled PNG all describe the same frame.

Return semantic_mask.png, semantic_label_map.json, semantic_bounding_boxes.json, semantic_bounding_boxes.png, the render settings, and a validation report. Include image dimensions, object-label count, visible-box count, missing-label count, renderer version, stage units, up axis, framebuffer orientation, and any validation failures.
```

## 3. Implement an OVPhysX drop test with OVD diagnostics and GIF playback

```text
Implement and run a bounded rigid-body drop test for [INPUT_USD] using the installed OVPhysX runtime.

Preflight the runtime and report its OVPhysX, PhysX SDK, OpenUSD, Python, device, and driver versions. Run OVPhysX in its compatible dedicated process. Do not modify the source USD. Record the source SHA-256 hash and author all test-specific changes in a task-owned overlay.

Inspect the stage units, up axis, physics scene, collision shapes, rigid bodies, mass and inertia properties, transforms, and dependencies. Select [DROP_BODY_PRIM] as the dynamic body. If a ground plane, collider, rigid-body API, mass property, or physics-scene setting is missing, author only the minimum required test opinions in the overlay and list each authored change in the report.

Configure OmniPVD recording before creating the PhysX instance. Load the composed USD, create reusable state bindings after loading completes, and run on [DEVICE: cpu or gpu] with timestep [DT, maximum 0.1 seconds] for [STEPS, 1 to 600]. Use deterministic initial conditions and record the selected body's position, orientation, linear velocity, and angular velocity at every step.

Produce:
- physics_test_overlay.usda
- physics_request.json containing the input identity and complete simulation settings
- pose_timeline.json or pose_timeline.csv containing time-indexed transforms
- drop_test.ovd finalized after releasing the PhysX instance
- ovd_report.md summarizing the OmniPVD recording, simulated actors, shapes, contacts, errors, warnings, and notable events
- physics_result.json containing terminal state, contact summary, final poses, validation checks, and artifact hashes

Treat drop_test.ovd as an OmniPVD diagnostic recording, not as a video. For visual playback, apply the recorded pose timeline to a renderable copy or non-destructive animation layer, render one image per sampled timestep with a compatible renderer, and encode the ordered frames as drop_test_playback.gif. Keep the camera, lighting, resolution, framing, color management, and frame timing fixed. Overlay the simulation time and frame number on each GIF frame. Do not rerun or approximate the physics during rendering; the GIF must replay the recorded poses.

Validate that the dynamic body falls under gravity, contacts the ground as expected, all poses remain finite, timestamps are monotonic, the GIF frame order matches the pose timeline, the OmniPVD file is finalized and nonempty, and the source USD hash remains unchanged. Report pass or fail separately for physics execution, OVD recording, pose extraction, visual rendering, GIF encoding, and artifact validation.

Return the overlay, request, pose timeline, OVD file, OVD report, physics result, rendered GIF, and a manifest of SHA-256 hashes. In the final summary include initial and final poses, fall distance, first-contact time, maximum speed, contact count, timestep, step count, device, elapsed time, software versions, authored test overrides, warnings, and validation failures.
```
