---
title:
  page: "Update an Existing Harness Engineering Playground Clone"
  nav: "Path Migration"
description:
  main: "Move an initialized deepagents submodule to the Harness Engineering Playground catalog path without losing local work."
  agent: "Provides guarded commands for clean pre-update migration and recovery after the example path changed."
keywords: ["git submodule migration", "harness engineering playground", "deepagents"]
topics: ["generative_ai", "ai_agents"]
tags: ["deepagents", "git", "submodule"]
content:
  type: how_to
  difficulty: intermediate
  audience: ["developer", "engineer"]
status: published
---

<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Update an Existing Harness Engineering Playground Clone

The Harness Engineering Playground moved from
`examples/harness-engineering-playground` to
`examples/tools/harness-engineering-playground`. Its `deepagents` submodule
moved with it.

Git does not move an initialized submodule worktree automatically. Use one of
the following procedures from the repository root. Both procedures stop before
removing a checkout that contains local work.

## Deinitialize before you update

Use this procedure when your current commit still contains the previous path:

```bash
old='examples/harness-engineering-playground/external/deepagents'
new='examples/tools/harness-engineering-playground/external/deepagents'

other_changes=$(git status --porcelain=v1 --untracked-files=all -- \
  . ":(exclude)$old" ":(exclude)$old/**")
if [ -n "$other_changes" ]; then
  printf '%s\n' "$other_changes"
  printf '%s\n' 'ABORT: preserve local repository changes before migration.' >&2
  exit 1
fi

if git -C "$old" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  expected=$(git rev-parse ":$old")
  actual=$(git -C "$old" rev-parse HEAD)
  submodule_changes=$(git -C "$old" status \
    --porcelain=v1 --untracked-files=all --ignored=matching)
  if [ "$actual" != "$expected" ] || [ -n "$submodule_changes" ]; then
    printf '%s\n' "$submodule_changes"
    printf '%s\n' 'ABORT: preserve local submodule changes before migration.' >&2
    exit 1
  fi
  git submodule deinit -- "$old"
fi

git pull --ff-only
git submodule sync -- "$new"
git submodule update --init -- "$new"
```

The commands do not use `--force`. Preserve any reported work before you
continue. Git can retain the previous object store under `.git/modules`. Do not
delete it because it can contain local branches or commits.

## Recover after you update

Use this procedure only when Git already switched to the new commit and left
the previous checkout as untracked content:

```bash
old='examples/harness-engineering-playground/external/deepagents'
new='examples/tools/harness-engineering-playground/external/deepagents'

return_branch=$(git symbolic-ref --quiet --short HEAD) || {
  printf '%s\n' 'ABORT: run recovery from a named branch.' >&2
  exit 1
}

other_changes=$(git status --porcelain=v1 --untracked-files=all -- \
  . ":(exclude)$old" ":(exclude)$old/**")
submodule_changes=$(git -C "$old" status \
  --porcelain=v1 --untracked-files=all --ignored=matching)
expected=$(git rev-parse ":$new")
actual=$(git -C "$old" rev-parse HEAD)

if [ -n "$other_changes" ] || [ -n "$submodule_changes" ] ||
   [ "$actual" != "$expected" ]; then
  printf '%s\n' "$other_changes" "$submodule_changes"
  printf '%s\n' 'ABORT: preserve local changes before recovery.' >&2
  exit 1
fi

move_commit=$(git log --no-renames --diff-filter=D -1 --format=%H -- "$old")
pre_move_commit=$(git rev-parse "$move_commit^1")
test -n "$(git ls-tree "$pre_move_commit" -- "$old")" || {
  printf '%s\n' 'ABORT: could not find the pre-move submodule revision.' >&2
  exit 1
}

git switch --detach "$pre_move_commit"
git submodule deinit -- "$old"
git switch "$return_branch"
git submodule sync -- "$new"
git submodule update --init -- "$new"
```

Do not copy the previous checkout over the new submodule.

## Verify the result

```bash
test ! -e examples/harness-engineering-playground
test -e examples/tools/harness-engineering-playground/external/deepagents/.git
git status --short
git submodule status -- \
  examples/tools/harness-engineering-playground/external/deepagents
```

The repository status must be clean. The submodule status must show only the
new path. Its status line must not start with `-`, `+`, or `U`.
