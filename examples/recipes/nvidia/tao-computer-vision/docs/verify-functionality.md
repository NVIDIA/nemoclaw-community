# Verify functionality

`scripts/verify.sh` confirms the recipe is wired correctly, then has the agent
drive a complete TAO **train → evaluate → inference** cycle on the host GPU from
a single prompt, using only public data and public weights.

## What it checks

1. **MCP server up** — the host `tao` MCP server is listening on `:9901`.
2. **Bridge reachable** — the sandbox can reach `host.openshell.internal:9901`
   (HTTP `200`/`400`/`406` all mean the server answered; `403` means the egress
   policy is blocking it; `000` means it is unreachable).
3. **Skills installed** — `/sandbox/tao-skills-external/skills/models` exists in
   the sandbox.
4. **End-to-end model run** — the agent stages a dataset and a backbone in the
   CPU shell, then runs three GPU jobs and reports the accuracy.

The core checks are cheap and run first; if any of them fails the script stops
before spending GPU time.

## The end-to-end demo

TAO's public HuggingFace weights are training **backbones**, not zero-shot
checkpoints, so there is no meaningful "just run inference" demo — a checkpoint
has to be trained first. The verifier therefore does the whole loop:

| Step | Where | What |
|---|---|---|
| Stage dataset | `tao_exec` (CPU) | Downloads [`AI-Lab-Makerere/beans`](https://huggingface.co/datasets/AI-Lab-Makerere/beans) (MIT; 3 classes, 1034 train / 133 val / 128 test) and unpacks it folder-per-class |
| Stage backbone | `tao_exec` (CPU) | Downloads [`timm/resnet18.a1_in1k`](https://huggingface.co/timm/resnet18.a1_in1k) (Apache-2.0) and strips its 1000-class ImageNet head |
| Train | `tao_run` (GPU) | `classification_pyt train`, `resnet_18`, 10 epochs, 224×224 |
| Evaluate | `tao_run` (GPU) | `classification_pyt evaluate` against the validation split |
| Inference | `tao_run` (GPU) | `classification_pyt inference` over the 128 held-out test images |

Neither asset is gated and neither needs a token. No NGC model checkpoint is
downloaded — only the TAO container image itself comes from NGC.

The ImageNet head must be stripped because it is shaped `[1000, 512]` while the
3-class model expects `[3, 512]`; PyTorch raises a size mismatch on load even
with `strict=False`. Dropping every `fc.*` tensor leaves the feature extractor,
which is the part that transfers.

## Expected result

```text
==> Core checks
  [ok]   tao MCP server is listening on :9901
  [ok]   sandbox reaches the tao MCP bridge (HTTP 406)
  [ok]   skill bank installed in the sandbox
==> Train -> evaluate -> inference on public data
  [ok]   agent trained a classifier on public data (val_acc_1 = 0.9248120188713074)
  [ok]   inference wrote 128 predictions to .../inference/.tao-jobs/<job>/result.csv
         /data/test/healthy/healthy_test.7.jpg,healthy,0.8023015260696411
         /data/test/healthy/healthy_test.23.jpg,healthy,0.9492994546890259
         /data/test/healthy/healthy_test.33.jpg,healthy,0.9586153626441956

VERIFY: PASS
```

`verify.sh` asserts against artifacts on the host, not against the agent's
prose: it reads `val_acc_1` out of the `status.json` files written during this
run and counts the prediction rows in the newest `result.csv`. The accuracy
floor is `TAO_VERIFY_MIN_ACC` (default `0.80`); a healthy run lands around
`0.92`. Because the spec sets `seed: 1234` and `cudnn.deterministic: true`, the
number is reproducible run to run for a given container image.

Budget **7–9 minutes** on a single modern GPU, plus a ~180 MB dataset download
the first time (and the one-off ~27 GB TAO image pull before that). Staging is
skipped on reruns, and the three GPU jobs are short — the training itself is
about a minute.

Validated on `nvcr.io/nvidia/tao/tao-toolkit:7.1.0-pyt` (`val_acc_1` 0.9173) and
on a 7.1.0 staging build (`0.9248`). The spec is identical on both; only the
last digits of the accuracy move.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `no tao MCP server on :9901` | bring-up did not finish, or the server exited | rerun `bash scripts/bring-up.sh`; check `~/tao-workspace/tao-mcp-server.log` |
| `ModuleNotFoundError: No module named 'mcp.server.fastmcp'` in the server log | the skill bank launches the server with an unpinned `uv run --with mcp`, and `mcp` 2.x removed that module | use a bank ref that pins `mcp<2` in `integrations/nemoclaw/setup-tao-nemoclaw.sh` |
| bring-up says `bridge OK` but the agent uses the wrong image | a server from an earlier bring-up is still on `:9901`; bring-up reuses a healthy server rather than restarting it | `bash scripts/tear-down.sh`, wait for `:9901` to free, then rerun bring-up |
| bridge returns `403` | egress policy not applied | rerun bring-up; confirm the `tao_mcp` policy is loaded |
| bridge returns `000` | server bound to the wrong interface | ensure it is bound to the Docker bridge gateway, not `0.0.0.0` |
| `no shell image available` from `tao_exec` | `TAO_SHELL_IMAGE` not resolved | ensure the bank's `versions.yaml` pins a `pyt` image, or set `TAO_SHELL_IMAGE` in `.env` |
| empty agent output, script returns in ~1 min | the long-lived `main` session held its write lock | expected to be handled — `verify.sh` runs in its own `--session-key`; check no other agent invocation is mid-flight |
| `no val_acc_1 was produced` | the train job never reached a terminal state | `nemoclaw <sandbox> agent --agent main -m "run tao_list and tao_logs for the last job"` |
| `val_acc_1` below the floor | backbone was not applied, so the model trained from scratch | confirm `backbone.pth` exists and the train log says `Loaded pretrained weights`; from scratch this dataset plateaus near `0.62` |
| size mismatch for `fc.weight` | the ImageNet head was not stripped | drop all `fc.*` tensors when staging the backbone |

## Going further

The same loop works for any TAO model in the bank — swap the skill and the
dataset contract. Two notes from validating this recipe:

- **Detection needs much more data.** RT-DETR on a 128-image COCO subset, even
  with a public ImageNet ResNet-50 backbone, only reaches `mAP ≈ 0.06` after 100
  epochs. DETR-family decoders need far more than a smoke-test dataset, which is
  why the verifier uses classification.
- **Backbones are interchangeable if the keys line up.** TAO's `resnet_18` /
  `resnet_50` use the stock torchvision/timm layout, so public timm checkpoints
  load with a full key match once the classifier head is removed.

To train on your own data, drop a folder-per-class dataset under
`~/tao-workspace/<name>/` with a `classes.txt`, and ask the agent to train on
it. It will run the skill's pre-flight, stage the backbone, launch the GPU job,
and report the result path.
