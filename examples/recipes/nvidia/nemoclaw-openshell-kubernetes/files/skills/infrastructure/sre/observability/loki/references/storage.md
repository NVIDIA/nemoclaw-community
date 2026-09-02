# Loki Storage Configuration Reference

## Storage Architecture

Loki manages three primary data types:

- **Chunks**: Compressed log entries stored in object stores
- **Indexes**: Stream metadata and references linking to chunks
- **Bloom Blocks**: Optional advanced indexes for accelerated search

## Index Engines

### TSDB (Recommended - Loki 2.8+)

The recommended index store for all new deployments.

**Benefits:**

- Stores index files directly in object storage
- More efficient, faster, and more scalable than BoltDB
- Feature parity with all previous approaches
- Dynamic query sharding (targets 300-600 MBs per shard)
- Index caching not required

**Configuration:**

```yaml
loki:
  schemaConfig:
    configs:
      - from: "2024-04-01"
        store: tsdb
        object_store: azure
        schema: v13
        index:
          prefix: loki_index_
          period: 24h

  storage_config:
    tsdb_shipper:
      active_index_directory: /loki/tsdb-index
      cache_location: /loki/tsdb-cache
      cache_ttl: 24h
```

### BoltDB Shipper (Legacy)

Suitable for Loki 2.0-2.7.x deployments only.

**Characteristics:**

- Index period MUST be 24 hours
- Requires compactor for deduplication
- Write deduplication disabled when replication factor > 1

## Object Store Backends

### AWS S3

**Required IAM Permissions:**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket",
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject"
      ],
      "Resource": [
        "arn:aws:s3:::my-loki-bucket",
        "arn:aws:s3:::my-loki-bucket/*"
      ]
    }
  ]
}
```

**Configuration:**

```yaml
loki:
  storage:
    type: s3
    s3:
      endpoint: s3.us-east-1.amazonaws.com
      region: us-east-1
      bucketnames: my-loki-bucket
      # Option 1: IAM Role (Recommended)
      # Use service account with IAM role annotation
      # Option 2: Access Keys
      accessKeyId: ${AWS_ACCESS_KEY_ID}
      secretAccessKey: ${AWS_SECRET_ACCESS_KEY}
      s3ForcePathStyle: false
      insecure: false
    bucketNames:
      chunks: my-loki-chunks
      ruler: my-loki-ruler
      admin: my-loki-admin
```

**SSE-KMS Encryption:**

```yaml
loki:
  storage:
    s3:
      sse:
        type: SSE-KMS
        kms_key_id: <kms-key-arn>
```

### Azure Blob Storage

**Authentication Methods:**

1. **User-Assigned Managed Identity (Recommended)**

```yaml
loki:
  storage:
    type: azure
    azure:
      accountName: mystorageaccount
      useManagedIdentity: true
      useFederatedToken: false
      userAssignedId: <identity-client-id>
      requestTimeout: 30s
```

2. **Workload Identity Federation**

```yaml
loki:
  podLabels:
    azure.workload.identity/use: "true"

serviceAccount:
  annotations:
    azure.workload.identity/client-id: <identity-client-id>

loki:
  storage:
    azure:
      accountName: mystorageaccount
      useManagedIdentity: false
      useFederatedToken: true
```

3. **Account Key (Dev only)**

```yaml
loki:
  storage:
    azure:
      accountName: mystorageaccount
      accountKey: ${AZURE_STORAGE_KEY}
```

4. **SAS Token**

```yaml
loki:
  storage:
    azure:
      accountName: mystorageaccount
      sasToken: ${AZURE_SAS_TOKEN}
```

**Required RBAC Role:**

- `Storage Blob Data Contributor` on the storage account

### Google Cloud Storage

**Configuration:**

```yaml
loki:
  storage:
    type: gcs
    gcs:
      bucketName: my-loki-bucket
      # Uses Workload Identity or service account JSON
      service_account: |
        ${GCS_SERVICE_ACCOUNT_JSON}
    bucketNames:
      chunks: chunks
      ruler: ruler
      admin: admin
```

### MinIO (On-Premises)

```yaml
loki:
  storage:
    type: s3
    s3:
      endpoint: minio.minio.svc:9000
      accessKeyId: ${MINIO_ACCESS_KEY}
      secretAccessKey: ${MINIO_SECRET_KEY}
      s3ForcePathStyle: true
      insecure: true   # Set false for TLS
    bucketNames:
      chunks: loki-chunks
      ruler: loki-ruler
      admin: loki-admin
```

### Filesystem (Development Only)

```yaml
loki:
  storage:
    type: filesystem
    filesystem:
      directory: /loki/chunks

  storage_config:
    filesystem:
      directory: /tmp/loki/
```

**Limitations:**

- NOT production-supported
- Directory limits at ~5.5M+ files
- Requires shared filesystem (NFS) for HA
- Durability depends on filesystem reliability

## Retention Configuration

**Enable Retention:**

```yaml
loki:
  compactor:
    retention_enabled: true
    retention_delete_delay: 2h
    retention_delete_worker_count: 50
    compaction_interval: 10m
    delete_request_store: azure

  limits_config:
    retention_period: 744h    # 31 days (minimum: 24h)
```

**Stream-Level Retention:**

```yaml
loki:
  limits_config:
    retention_period: 744h    # Default

    retention_stream:
      - selector: '{environment="dev"}'
        priority: 1
        period: 168h          # 7 days

      - selector: '{environment="prod"}'
        priority: 1
        period: 2160h         # 90 days

      - selector: '{namespace="audit"}'
        priority: 2
        period: 8760h         # 1 year
```

**Per-Tenant Overrides:**

```yaml
# runtime-config.yaml
overrides:
  tenant-a:
    retention_period: 2160h
  tenant-b:
    retention_period: 720h
```

## Write Ahead Log (WAL)

**Purpose:** Records incoming data for crash recovery.

**Configuration:**

```yaml
loki:
  ingester:
    wal:
      enabled: true
      dir: /loki/wal
      checkpoint_duration: 5m
      replay_memory_ceiling: 4GB   # ~75% of available memory
```

**Requirements:**

- Use StatefulSets with persistent volumes
- Each ingester must have unique WAL directory
- Expect ~10-15GB disk usage per ingester

**Monitoring Metrics:**

- `loki_ingester_wal_records_logged`
- `loki_ingester_wal_logged_bytes_total`
- `loki_ingester_wal_corruptions_total`
- `loki_ingester_wal_disk_full_failures_total`

## Caching

### Results Cache (Frontend)

```yaml
loki:
  query_frontend:
    results_cache:
      cache:
        memcached_client:
          host: loki-memcached-frontend.monitoring.svc
          service: memcached-client
          timeout: 500ms
          max_idle_conns: 16
          update_interval: 1m
```

### Chunks Cache

```yaml
loki:
  chunk_store_config:
    chunk_cache_config:
      memcached_client:
        host: loki-memcached-chunks.monitoring.svc
        service: memcached-client
        timeout: 500ms
        max_idle_conns: 16
        batch_size: 256
        parallelism: 10
```

### Memcached Deployment

```yaml
# Chunks cache (larger)
memcached-chunks:
  replicas: 3
  args:
    - --memory-limit=4096
    - --max-item-size=2m
    - --conn-limit=1024

# Results cache (smaller)
memcached-frontend:
  replicas: 3
  args:
    - --memory-limit=1024
    - --max-item-size=5m
    - --conn-limit=1024
```

## Compaction

**Configuration:**

```yaml
loki:
  compactor:
    working_directory: /loki/compactor
    compaction_interval: 10m
    retention_enabled: true
    retention_delete_delay: 2h
    retention_delete_worker_count: 50
    delete_request_store: azure
```

**Component Requirements:**

- Must run as singleton instance
- Requires delete permissions on object storage
- Handles index deduplication and merging

## Schema Migration

**Adding New Schema:**

```yaml
loki:
  schemaConfig:
    configs:
      # Old schema (keep for historical data)
      - from: "2023-01-01"
        store: boltdb-shipper
        object_store: azure
        schema: v12
        index:
          prefix: loki_index_
          period: 24h

      # New schema (future date, UTC 00:00:00)
      - from: "2024-04-01"
        store: tsdb
        object_store: azure
        schema: v13
        index:
          prefix: loki_index_
          period: 24h
```

**Rules:**

- `from` date must be in future (UTC 00:00:00)
- Schema changes are irreversible
- Multiple schemas can coexist
- Queries span schemas transparently

## Storage Troubleshooting

### Azure Container Not Found

```bash
az storage container create --name loki-chunks --account-name <storage>
az storage container create --name loki-ruler --account-name <storage>
az storage container create --name loki-admin --account-name <storage>
```

### Azure Authorization Failure

```bash
# Check role assignments
az role assignment list --scope <storage-scope> --query "[?principalId=='<principal-id>']"

# Assign role if missing
az role assignment create \
  --role "Storage Blob Data Contributor" \
  --assignee-object-id <principal-id> \
  --scope <storage-scope>

# Restart ingester to refresh token
kubectl delete pod -n monitoring <ingester-pod>
```

### S3 Access Denied

```bash
# Verify IAM policy
aws iam get-policy --policy-arn <policy-arn>

# Test bucket access
aws s3 ls s3://my-loki-bucket/
```

### Compactor Issues

```bash
# Check compactor logs
kubectl logs -n monitoring -l app.kubernetes.io/component=compactor --tail=200

# Verify compactor is running as singleton
kubectl get pods -n monitoring -l app.kubernetes.io/component=compactor
```
