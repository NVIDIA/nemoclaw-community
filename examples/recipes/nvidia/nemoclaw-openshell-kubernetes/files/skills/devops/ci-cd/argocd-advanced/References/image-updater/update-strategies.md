# ArgoCD Image Updater - Update Strategies

ArgoCD Image Updater supports four update strategies to determine which image version to use when updating workloads.

## Strategy Overview

| Strategy | Best For | Tag Format |
|----------|----------|------------|
| `semver` | Production, semantic versions | `v1.2.3`, `1.2.3`, `1.2.3-rc1` |
| `newest-build` | CI/CD, dev environments | Any (uses build time) |
| `digest` | Mutable tags like `latest` | `latest`, `main`, `dev` |
| `alphabetical` | CalVer, custom schemes | `2024.01.15`, `20240115` |

## Semver Strategy

The `semver` strategy selects images based on semantic versioning rules.

### Basic Configuration

```yaml
spec:
  applicationRefs:
    - namePattern: "my-app"
      images:
        - alias: "app"
          imageName: "myregistry/app"
          commonUpdateSettings:
            updateStrategy: "semver"
```

### Version Constraints

Specify constraints in the image tag:

```yaml
images:
  - alias: "app"
    imageName: "myregistry/app:1.x"    # Any 1.x.x version
```

#### Constraint Syntax

| Constraint | Meaning | Example Matches |
|------------|---------|-----------------|
| `1.x` or `1.*` | Any 1.x.x | 1.0.0, 1.5.3, 1.99.0 |
| `1.2.x` | Any 1.2.x | 1.2.0, 1.2.15 |
| `>=1.0.0` | Greater or equal | 1.0.0, 2.5.0, 10.0.0 |
| `<2.0.0` | Less than | 0.1.0, 1.9.9 |
| `>=1.0.0 <2.0.0` | Range | 1.0.0 to 1.99.99 |
| `~1.2.3` | Patch updates | 1.2.3, 1.2.4, 1.2.99 |
| `^1.2.3` | Minor updates | 1.2.3, 1.3.0, 1.99.0 |

### Pre-release Handling

By default, pre-release versions (e.g., `1.0.0-rc1`) are excluded.

To include pre-releases:

```yaml
images:
  - alias: "app"
    imageName: "myregistry/app:1.x"
    commonUpdateSettings:
      updateStrategy: "semver"
      allowPreRelease: true
```

### Tag Filtering with Semver

```yaml
images:
  - alias: "app"
    imageName: "myregistry/app"
    commonUpdateSettings:
      updateStrategy: "semver"
    tagMatch:
      pattern: "^v[0-9]+\\.[0-9]+\\.[0-9]+$"  # Only vX.Y.Z tags
```

## Newest-Build Strategy

Selects the image with the most recent build timestamp from the registry.

### Configuration

```yaml
spec:
  applicationRefs:
    - namePattern: "dev-*"
      images:
        - alias: "app"
          imageName: "myregistry/app"
          commonUpdateSettings:
            updateStrategy: "newest-build"
```

### Use Cases

- Development environments
- CI/CD pipelines with timestamp-based tags
- Feature branches

### Tag Filtering

Combine with tag filtering to select from specific tags:

```yaml
images:
  - alias: "app"
    imageName: "myregistry/app"
    commonUpdateSettings:
      updateStrategy: "newest-build"
    tagMatch:
      pattern: "^main-[a-f0-9]{7}$"  # main-<short-sha>
```

### Sorting by Build Time

The strategy uses the image creation timestamp from the registry metadata, not the tag name.

## Digest Strategy

Tracks mutable tags by their SHA256 digest. Updates when the digest changes, even if the tag stays the same.

### Configuration

```yaml
spec:
  applicationRefs:
    - namePattern: "staging-*"
      images:
        - alias: "app"
          imageName: "myregistry/app:latest"
          commonUpdateSettings:
            updateStrategy: "digest"
```

### Use Cases

- Tracking `latest` tag
- Branch-based tags (`main`, `develop`)
- Environment tags (`staging`, `production`)

### How It Works

1. Image Updater fetches the current digest for the tag
2. Compares with the digest currently deployed
3. Updates if digests differ
4. Stores the new digest in Argo CD application

### Important Notes

- The tag itself doesn't change
- Argo CD stores the pinned digest
- Useful when you can't change tagging strategy

## Alphabetical Strategy

Sorts tags lexicographically and selects the "highest" one.

### Configuration

```yaml
spec:
  applicationRefs:
    - namePattern: "calver-*"
      images:
        - alias: "app"
          imageName: "myregistry/app"
          commonUpdateSettings:
            updateStrategy: "alphabetical"
```

### Use Cases

- Calendar Versioning (CalVer): `2024.01.15`, `2024.02.01`
- Date-based tags: `20240115`, `20240201`
- Custom schemes where lexical sorting works

### Sorting Behavior

Tags are sorted as strings (lexicographically), character by character from left to right:

- `2024.01.15` < `2024.02.01` < `2024.12.31` ✓ Works correctly (zero-padded)
- `a` < `b` < `z` ✓ Works correctly
- `1` < `10` < `2` ✗ **Incorrect!** (string sorting compares `'1'` < `'2'`, not numeric values)

> **⚠️ Critical Warning:** Alphabetical sorting treats numbers as strings. This means:
>
> - `v10` sorts **before** `v2` (because `'1'` < `'2'`)
> - `2024.1.5` sorts **after** `2024.12.1` (because `'5'` > `'1'`)
>
> **When to use `alphabetical`:** Only use this strategy with consistently formatted, zero-padded tags like:
>
> - CalVer: `2024.01.15`, `2024.12.31` (always `YYYY.MM.DD`)
> - Date-based: `20240115`, `20241231` (always `YYYYMMDD`)
>
> **When NOT to use `alphabetical`:**
>
> - Semantic versions (`v1.2.3`, `v10.0.0`) → Use `semver` strategy instead
> - Non-zero-padded dates (`2024.1.5`) → Fix tagging or use `newest-build`

### Tag Filtering for Correct Sorting

Ensure consistent tag format with filtering:

```yaml
images:
  - alias: "app"
    imageName: "myregistry/app"
    commonUpdateSettings:
      updateStrategy: "alphabetical"
    tagMatch:
      pattern: "^[0-9]{4}\\.[0-9]{2}\\.[0-9]{2}$"  # YYYY.MM.DD
```

## Tag Filtering

All strategies support tag filtering to control which tags are considered.

### Allow Tags (Regex)

```yaml
images:
  - alias: "app"
    imageName: "myregistry/app"
    tagMatch:
      pattern: "^v[0-9]+\\.[0-9]+\\.[0-9]+$"
```

### Ignore Tags (Regex)

```yaml
images:
  - alias: "app"
    imageName: "myregistry/app"
    tagIgnore:
      pattern: ".*-rc[0-9]*$"  # Ignore release candidates
```

### Combined Filtering

```yaml
images:
  - alias: "app"
    imageName: "myregistry/app"
    tagMatch:
      pattern: "^v[0-9]+"  # Must start with v and number
    tagIgnore:
      pattern: ".*-(alpha|beta|rc).*"  # Exclude pre-releases
```

## Strategy Selection Guide

```
Is it semantic versioning (vX.Y.Z)?
├── Yes → Use 'semver'
└── No
    ├── Do you track mutable tags (latest, main)?
    │   ├── Yes → Use 'digest'
    │   └── No
    │       ├── Is it CalVer or lexically sortable?
    │       │   ├── Yes → Use 'alphabetical'
    │       │   └── No → Use 'newest-build'
```

## Per-Image Strategy Override

Override strategy per image when applications use mixed tagging:

```yaml
spec:
  commonUpdateSettings:
    updateStrategy: "semver"  # Default
  applicationRefs:
    - namePattern: "my-app"
      images:
        - alias: "backend"
          imageName: "myregistry/backend"
          # Uses default semver
        - alias: "frontend"
          imageName: "myregistry/frontend:main"
          commonUpdateSettings:
            updateStrategy: "digest"  # Override for this image
```
