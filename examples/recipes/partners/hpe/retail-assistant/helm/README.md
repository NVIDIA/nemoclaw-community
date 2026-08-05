# NemoClaw Retail Demo — Helm Chart

Deploys the full retail assistant stack on Kubernetes.

> For common documentation (LLM endpoint setup, identity files, adding users, database schema), see the [root README](../README.md).

## Deployments

- **nemoclaw** - workspace container that runs the NemoClaw installer, onboards the sandbox, and applies all post-deploy fixes
- **retail-api** - FastAPI backend with JWT authentication and PostgreSQL RBAC
- **postgres** - PostgreSQL database with schema, RLS policies, and seed data

A one-shot `postgres-seed` Job populates the database with synthetic retail data on first install.

## Install

```bash
helm install retail-assistant ./helm \
  --namespace nemoclaw \
  --create-namespace \
  -f my-values.yaml
```

## Key Values

Edit `values.yaml` or pass overrides with `--set`:

| Value | Description |
|---|---|
| `workspace.openaiBaseUrl` | OpenAI-compatible base URL incl. `/v1` (e.g. `http://ip:port/v1`) |
| `workspace.socatInferencePort` | Port for the inference socat proxy. Default `8000`. Change if port 8000 is busy on the node. |
| `workspace.model` | Model name (e.g. `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-FP8`) |
| `workspace.agent_name` | OpenShell sandbox name |
| `telegram.botToken` | Telegram bot token from @BotFather |
| `telegram.allowedUserIds` | Comma-separated Telegram user IDs |
| `telegramAuth` | List of `{telegramId, email}` mappings for DB auth |
| `postgres.storageClass` | StorageClass for the PostgreSQL PVC |
| `retailApi.image` | Retail API container image |
| `openclaw.streamingMode` | Telegram streaming: `partial` (token-by-token) or `full` (wait for complete response). Default: `partial` |
| `openclaw.toolProgress` | Show tool-call progress messages in Telegram while agent is working. Default: `false` |
| `openclaw.maxTokens` | Max output tokens per model response. Lower = faster. Default: `8192` |
| `ingress.enabled` | Enable ingress for the NemoClaw dashboard |
| `ingress.host` | Dashboard hostname |

## Upgrade

```bash
helm upgrade retail-assistant ./helm \
  --namespace nemoclaw \
  -f my-values.yaml
```

## Adding a User

### Step 1 — Add to allowed user list

Add the Telegram ID to `telegram.allowedUserIds` in `values.yaml`:

```yaml
telegram:
  allowedUserIds: "existing_id,NEW_TELEGRAM_ID"
```

### Step 2 — Map Telegram ID to an employee

Add a row to `files/csv/TelegramAuth.csv`:

```csv
telegram_id,employee_id
NEW_TELEGRAM_ID,<employee_id>
```

### Step 3 (optional) — Create the employee record

Add a row to `files/csv/Employees.csv`:

```csv
employee_id,first_name,last_name,role,store_id,email
<next_id>,First,Last,<role>,<store_id or blank>,first.last@retaildemo.com
```

Then upgrade the release to reseed the database:

```bash
helm upgrade retail-assistant ./helm --namespace nemoclaw -f my-values.yaml
```

> ⚠️ If the PostgreSQL PVC already exists with old data, delete it first so the seed job runs fresh:
> ```bash
> kubectl delete pvc -n nemoclaw -l app=postgres
> ```

## Uninstall

```bash
helm uninstall retail-assistant --namespace nemoclaw
```

> **Note:** The PostgreSQL PVC is not deleted automatically. Remove it manually if you want to reset the database:
> ```bash
> kubectl delete pvc -n nemoclaw -l app=postgres
> ```
