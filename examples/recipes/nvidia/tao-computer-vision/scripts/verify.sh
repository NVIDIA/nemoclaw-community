#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Verify the TAO recipe: the host tao MCP server is up, the sandbox reaches it,
# the skill bank is installed, and the agent drives a complete TAO
# train -> evaluate -> inference cycle on the host GPU using only public data.

set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
cd "$ROOT"
[ -f .env ] && { set -a; . ./.env; set +a; }

SANDBOX="${TAO_SANDBOX:-tao}"
WORKSPACE="${TAO_WORKSPACE:-$HOME/tao-workspace}"
PORT=9901
# The demo fine-tunes for 10 epochs from an ImageNet backbone; a healthy run
# lands well above this floor. Lower it only to debug, never to pass a bad run.
MIN_ACC="${TAO_VERIFY_MIN_ACC:-0.80}"
fail=0
pass() { echo "  [ok]   $*"; }
bad()  { echo "  [FAIL] $*"; fail=1; }

echo "==> Core checks"
if ss -tlnp 2>/dev/null | grep -q ":$PORT"; then pass "tao MCP server is listening on :$PORT"
else bad "no tao MCP server on :$PORT (run scripts/bring-up.sh)"; fi

CODE=$(nemoclaw "$SANDBOX" exec -- curl -sS --max-time 8 -o /dev/null -w '%{http_code}' \
       "http://host.openshell.internal:$PORT/mcp" 2>/dev/null || echo 000)
case "$CODE" in
  200|400|406) pass "sandbox reaches the tao MCP bridge (HTTP $CODE)";;
  *)           bad  "sandbox cannot reach the tao MCP bridge (HTTP $CODE)";;
esac

if nemoclaw "$SANDBOX" exec -- bash -c 'ls /sandbox/tao-skills-external/skills/models >/dev/null 2>&1'; then
  pass "skill bank installed in the sandbox"
else bad "skill bank not installed in the sandbox"; fi

[ "$fail" -eq 0 ] || { echo; echo "VERIFY: FAIL (core checks)"; exit 1; }

echo "==> Train -> evaluate -> inference on public data"
echo "    The agent stages the dataset and backbone itself, then runs three GPU"
echo "    jobs. The first run downloads ~180 MB and takes a few minutes."

STAMP="$WORKSPACE/.verify-start"
: > "$STAMP"

read -r -d '' PROMPT <<'AGENT_PROMPT'
Train, evaluate, and run inference on a TAO image classifier end to end, using
only public data and public weights. No NGC model checkpoints. Use plain
training: automl_policy off, no HPO, no AutoML. Do everything through the tao
MCP tools; read the tao-train-image-classification skill for the spec schema.

1. Stage the dataset in the tao_exec CPU shell. Skip any step whose output
   already exists. The beans leaf-disease dataset is public (MIT, 3 classes):

     mkdir -p /workspace/beans/backbone
     for s in train validation test; do
       curl -sSL -o /workspace/beans/$s.zip \
         https://huggingface.co/datasets/AI-Lab-Makerere/beans/resolve/main/data/$s.zip
       unzip -q -o /workspace/beans/$s.zip -d /workspace/beans
     done

   That unpacks folder-per-class directories train/, validation/ and test/, each
   holding angular_leaf_spot/, bean_rust/ and healthy/. Write those three names,
   one per line, to /workspace/beans/classes.txt.

2. Stage the public ImageNet backbone in the tao_exec shell (Apache-2.0, no
   token needed):

     curl -sSL -o /workspace/beans/backbone/resnet18_imagenet.pth \
       https://huggingface.co/timm/resnet18.a1_in1k/resolve/main/pytorch_model.bin

   Its 1000-class ImageNet head does not fit a 3-class model and torch raises a
   size mismatch on load, so strip every tensor whose key starts with "fc." and
   save the rest as /workspace/beans/backbone/backbone.pth.

3. tao_pull the TAO PyTorch image, then run three tao_run jobs with
   data_subdir "beans". /workspace/beans is mounted at /data inside each job.
   Use backbone type resnet_18 with head in_channels 512, num_classes 3,
   img_size 224, batch_size 64, wandb disabled, and point
   dataset.train_dataset.images_dir at /data/train,
   dataset.val_dataset.images_dir at /data/validation,
   dataset.test_dataset.images_dir at /data/test and
   dataset.classes_file at /data/classes.txt.

     a. classification_pyt train - 10 epochs, adamw, lr 3e-4, 1 warmup epoch,
        model.backbone.pretrained_backbone_path /data/backbone/backbone.pth
     b. classification_pyt evaluate - checkpoint from the train results dir
     c. classification_pyt inference - the same checkpoint

   Poll tao_status until each job reaches a terminal state before starting the
   next one - do not sleep in your own shell - and read the checkpoint filename
   out of the train results directory rather than guessing it.

4. Report the final val_acc_1, the host path of the inference result.csv, and
   the first few predictions in it.
AGENT_PROMPT

# Run in a session of its own. Sharing the long-lived interactive `main` session
# makes concurrent or back-to-back runs fail on its session write lock, and a
# fresh session also keeps the demo reproducible.
OUT=$(nemoclaw "$SANDBOX" agent --agent main --session-key "tao-verify-$$" \
        -m "$PROMPT" 2>/dev/null)

# Assert against host-side artifacts, not the agent's prose. The agent chooses
# its own results_subdir, so scan the whole workspace and keep only files this
# run produced.
ACC=$(find "$WORKSPACE" -name status.json -newer "$STAMP" -exec cat {} + 2>/dev/null \
      | grep -oE '"val_acc_1":[[:space:]]*[0-9.]+' | grep -oE '[0-9.]+$' | sort -g | tail -1)
# Inference runs last, so the newest result.csv is its own.
CSV=$(find "$WORKSPACE" -name result.csv -newer "$STAMP" -printf '%T@ %p\n' 2>/dev/null \
      | sort -gr | head -1 | cut -d' ' -f2-)
rm -f "$STAMP"

if [ -n "$ACC" ] && awk "BEGIN{exit !($ACC >= $MIN_ACC)}"; then
  pass "agent trained a classifier on public data (val_acc_1 = $ACC)"
elif [ -n "$ACC" ]; then
  bad "training ran but val_acc_1 = $ACC is below $MIN_ACC"
else
  bad "no val_acc_1 was produced - the training job did not complete"
fi

if [ -n "$CSV" ] && [ "$(grep -c . "$CSV")" -gt 1 ]; then
  pass "inference wrote $(( $(grep -c . "$CSV") - 1 )) predictions to $CSV"
  sed -n '2,4p' "$CSV" | sed 's/^/         /'
else
  bad "inference produced no result.csv under $WORKSPACE/results"
fi

if [ "$fail" -ne 0 ]; then
  echo "  --- agent output (tail) ---"; tail -n 12 <<<"$OUT" | sed 's/^/  /'
fi

echo ""
[ "$fail" -eq 0 ] && echo "VERIFY: PASS" || echo "VERIFY: FAIL"
exit "$fail"
