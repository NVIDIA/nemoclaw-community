# ArgoCD API Reference

Complete REST API endpoint documentation for ArgoCD.

## Base URL and Headers

```
Base URL: https://{server}/api/v1
Headers:
  Authorization: Bearer {token}
  Content-Type: application/json
```

## Applications API

### List Applications

```
GET /api/v1/applications
Query params: ?projects=default&selector=app%3Dmyapp&appNamespace=argocd
```

### Get Application

```
GET /api/v1/applications/{name}
Query params: ?appNamespace=argocd&project=default
```

### Create Application

```
POST /api/v1/applications
Query params: ?upsert=true&validate=true

Body:
{
  "metadata": {
    "name": "string",
    "namespace": "argocd",
    "labels": {},
    "annotations": {},
    "finalizers": ["resources-finalizer.argocd.argoproj.io"]
  },
  "spec": {
    "project": "default",
    "source": {
      "repoURL": "string",
      "path": "string",
      "targetRevision": "HEAD",
      "helm": {
        "releaseName": "string",
        "valueFiles": ["values.yaml"],
        "values": "string",
        "parameters": [{"name": "string", "value": "string"}],
        "fileParameters": [{"name": "string", "path": "string"}]
      },
      "kustomize": {
        "namePrefix": "string",
        "nameSuffix": "string",
        "images": ["image:tag"],
        "commonLabels": {},
        "commonAnnotations": {}
      },
      "directory": {
        "recurse": true,
        "jsonnet": {},
        "exclude": "string",
        "include": "string"
      }
    },
    "sources": [],  // Multi-source support
    "destination": {
      "server": "https://kubernetes.default.svc",
      "namespace": "string",
      "name": "string"  // Cluster name alternative
    },
    "syncPolicy": {
      "automated": {
        "prune": true,
        "selfHeal": true,
        "allowEmpty": false
      },
      "syncOptions": [
        "CreateNamespace=true",
        "PrunePropagationPolicy=foreground",
        "PruneLast=true",
        "Replace=false",
        "ApplyOutOfSyncOnly=true",
        "ServerSideApply=true"
      ],
      "retry": {
        "limit": 5,
        "backoff": {
          "duration": "5s",
          "factor": 2,
          "maxDuration": "3m"
        }
      }
    },
    "ignoreDifferences": [
      {
        "group": "apps",
        "kind": "Deployment",
        "name": "string",
        "namespace": "string",
        "jsonPointers": ["/spec/replicas"],
        "jqPathExpressions": [".spec.replicas"],
        "managedFieldsManagers": ["kube-controller-manager"]
      }
    ],
    "revisionHistoryLimit": 10
  }
}
```

### Update Application

```
PUT /api/v1/applications/{name}
Query params: ?validate=true&project=default

Body: Same as create
```

### Patch Application

```
PATCH /api/v1/applications/{name}
Query params: ?project=default

Body (JSON Patch):
[
  {"op": "replace", "path": "/spec/source/targetRevision", "value": "v1.0.0"}
]
```

### Delete Application

```
DELETE /api/v1/applications/{name}
Query params: ?cascade=true&propagationPolicy=foreground&appNamespace=argocd
```

### Sync Application

```
POST /api/v1/applications/{name}/sync

Body:
{
  "revision": "HEAD",
  "prune": true,
  "dryRun": false,
  "strategy": {
    "apply": {"force": false},
    "hook": {"force": false}
  },
  "resources": [
    {
      "group": "apps",
      "kind": "Deployment",
      "name": "nginx",
      "namespace": "default"
    }
  ],
  "syncOptions": {
    "items": ["CreateNamespace=true", "PruneLast=true"]
  },
  "retryStrategy": {
    "limit": 3,
    "backoff": {"duration": "5s", "factor": 2, "maxDuration": "1m"}
  },
  "infos": [{"name": "triggeredBy", "value": "CI"}]
}
```

### Rollback Application

```
POST /api/v1/applications/{name}/rollback

Body:
{
  "id": 2,  // History ID from /history endpoint
  "prune": true,
  "dryRun": false
}
```

### Terminate Operation

```
DELETE /api/v1/applications/{name}/operation
```

### Get Resource Tree

```
GET /api/v1/applications/{name}/resource-tree
Query params: ?appNamespace=argocd
```

### Get Managed Resources

```
GET /api/v1/applications/{name}/managed-resources
Query params: ?namespace=default&name=nginx&kind=Deployment&group=apps
```

### Get Application Logs

```
GET /api/v1/applications/{name}/logs
Query params: ?namespace=default&podName=nginx-xxx&container=nginx&sinceSeconds=3600&tailLines=100&follow=false
```

### Get Application Events

```
GET /api/v1/applications/{name}/events
```

### Get Application History

```
GET /api/v1/applications/{name}/revisions/{revision}/metadata
```

### Resource Actions

```
POST /api/v1/applications/{name}/resource/actions
Query params: ?namespace=default&resourceName=nginx&kind=Deployment&group=apps&version=v1

Body: "restart"  // Action name as JSON string
```

### Get Resource Actions

```
GET /api/v1/applications/{name}/resource/actions
Query params: ?namespace=default&resourceName=nginx&kind=Deployment&group=apps&version=v1
```

### Delete Resource

```
DELETE /api/v1/applications/{name}/resource
Query params: ?namespace=default&resourceName=nginx&kind=Deployment&group=apps&version=v1&force=false&orphan=false
```

## ApplicationSets API

### List ApplicationSets

```
GET /api/v1/applicationsets
Query params: ?projects=default&selector=app%3Dmyapp&appsetNamespace=argocd
```

### Get ApplicationSet

```
GET /api/v1/applicationsets/{name}
Query params: ?appsetNamespace=argocd
```

### Create ApplicationSet

```
POST /api/v1/applicationsets
Query params: ?upsert=true

Body:
{
  "metadata": {
    "name": "string",
    "namespace": "argocd"
  },
  "spec": {
    "goTemplate": true,
    "goTemplateOptions": ["missingkey=error"],
    "generators": [
      {
        "list": {
          "elements": [
            {"cluster": "dev", "url": "https://dev.example.com"}
          ]
        }
      },
      {
        "clusters": {
          "selector": {
            "matchLabels": {"environment": "production"}
          }
        }
      },
      {
        "git": {
          "repoURL": "https://github.com/org/repo.git",
          "revision": "HEAD",
          "directories": [{"path": "apps/*"}],
          "files": [{"path": "apps/*/config.json"}]
        }
      },
      {
        "matrix": {
          "generators": [
            {"clusters": {}},
            {"git": {"directories": [{"path": "apps/*"}]}}
          ]
        }
      },
      {
        "merge": {
          "mergeKeys": ["name"],
          "generators": []
        }
      },
      {
        "pullRequest": {
          "github": {
            "owner": "org",
            "repo": "repo",
            "tokenRef": {"secretName": "github-token", "key": "token"},
            "labels": ["preview"]
          }
        }
      },
      {
        "scmProvider": {
          "github": {
            "organization": "myorg",
            "tokenRef": {"secretName": "github-token", "key": "token"}
          },
          "filters": [{"repositoryMatch": "^app-.*"}]
        }
      }
    ],
    "template": {
      "metadata": {
        "name": "{{.cluster}}-{{.path.basename}}",
        "labels": {},
        "annotations": {}
      },
      "spec": {
        "project": "default",
        "source": {
          "repoURL": "https://github.com/org/repo.git",
          "targetRevision": "HEAD",
          "path": "{{.path.path}}"
        },
        "destination": {
          "server": "{{.url}}",
          "namespace": "{{.path.basename}}"
        }
      }
    },
    "syncPolicy": {
      "preserveResourcesOnDeletion": false,
      "applicationsSync": "sync"
    },
    "strategy": {
      "type": "RollingSync",
      "rollingSync": {
        "steps": [
          {"matchExpressions": [{"key": "env", "operator": "In", "values": ["dev"]}]},
          {"matchExpressions": [{"key": "env", "operator": "In", "values": ["prod"]}], "maxUpdate": "25%"}
        ]
      }
    }
  }
}
```

### Delete ApplicationSet

```
DELETE /api/v1/applicationsets/{name}
Query params: ?appsetNamespace=argocd
```

## Projects API

### List Projects

```
GET /api/v1/projects
```

### Get Project

```
GET /api/v1/projects/{name}
```

### Create Project

```
POST /api/v1/projects

Body:
{
  "metadata": {
    "name": "string"
  },
  "spec": {
    "description": "string",
    "sourceRepos": ["https://github.com/org/*", "*"],
    "sourceNamespaces": ["argocd"],
    "destinations": [
      {
        "server": "https://kubernetes.default.svc",
        "namespace": "team-*",
        "name": "*"
      }
    ],
    "clusterResourceWhitelist": [
      {"group": "", "kind": "Namespace"},
      {"group": "rbac.authorization.k8s.io", "kind": "*"}
    ],
    "clusterResourceBlacklist": [],
    "namespaceResourceWhitelist": [
      {"group": "*", "kind": "*"}
    ],
    "namespaceResourceBlacklist": [],
    "roles": [
      {
        "name": "developer",
        "description": "Developer role",
        "policies": [
          "p, proj:myproject:developer, applications, get, myproject/*, allow",
          "p, proj:myproject:developer, applications, sync, myproject/*, allow"
        ],
        "groups": ["team-developers"],
        "jwtTokens": []
      }
    ],
    "syncWindows": [
      {
        "kind": "allow",
        "schedule": "0 22 * * *",
        "duration": "2h",
        "applications": ["*"],
        "namespaces": ["*"],
        "clusters": ["*"],
        "manualSync": true,
        "timeZone": "America/New_York"
      }
    ],
    "orphanedResources": {
      "warn": true,
      "ignore": [{"group": "", "kind": "ConfigMap", "name": "kube-root-ca.crt"}]
    },
    "signatureKeys": [{"keyID": "string"}],
    "permitOnlyProjectScopedClusters": false
  }
}
```

### Update Project

```
PUT /api/v1/projects/{name}

Body: Same as create
```

### Delete Project

```
DELETE /api/v1/projects/{name}
```

### Create Project Role Token

```
POST /api/v1/projects/{project}/roles/{role}/token

Body:
{
  "expiresIn": 86400,  // Seconds (24 hours)
  "id": "token-identifier",
  "description": "CI/CD token"
}
```

### Delete Project Role Token

```
DELETE /api/v1/projects/{project}/roles/{role}/token/{iat}
```

## Repositories API

### List Repositories

```
GET /api/v1/repositories
Query params: ?repo=https://github.com/org/repo&forceRefresh=true
```

### Get Repository

```
GET /api/v1/repositories/{repo}
Query params: ?forceRefresh=true
```

### Create Repository

```
POST /api/v1/repositories
Query params: ?upsert=true

Body:
{
  "repo": "https://github.com/org/repo.git",
  "type": "git",  // git, helm
  "name": "my-repo",
  "project": "default",
  "username": "git",
  "password": "token",
  "sshPrivateKey": "string",
  "insecure": false,
  "tlsClientCertData": "string",
  "tlsClientCertKey": "string",
  "enableLfs": false,
  "enableOCI": false,
  "githubAppId": 12345,
  "githubAppInstallationId": 67890,
  "githubAppPrivateKey": "string",
  "proxy": "http://proxy:8080",
  "forceHttpBasicAuth": false,
  "gcpServiceAccountKey": "string"
}
```

### Update Repository

```
PUT /api/v1/repositories/{repo}

Body: Same as create
```

### Delete Repository

```
DELETE /api/v1/repositories/{repo}
Query params: ?forceRefresh=false
```

### Validate Repository

```
POST /api/v1/repositories/{repo}/validate
```

### Get Repository Apps

```
GET /api/v1/repositories/{repo}/apps
Query params: ?revision=HEAD&appName=myapp&appProject=default
```

## Repository Credentials API

### List Repository Credentials

```
GET /api/v1/repocreds
Query params: ?url=https://github.com/org/
```

### Create Repository Credentials

```
POST /api/v1/repocreds
Query params: ?upsert=true

Body:
{
  "url": "https://github.com/myorg/",
  "username": "git",
  "password": "token",
  "sshPrivateKey": "string",
  "type": "git",
  "tlsClientCertData": "string",
  "tlsClientCertKey": "string",
  "githubAppId": 12345,
  "githubAppInstallationId": 67890,
  "githubAppPrivateKey": "string",
  "enableOCI": false,
  "proxy": "http://proxy:8080",
  "forceHttpBasicAuth": false,
  "gcpServiceAccountKey": "string"
}
```

### Update Repository Credentials

```
PUT /api/v1/repocreds/{creds.url}

Body: Same as create
```

### Delete Repository Credentials

```
DELETE /api/v1/repocreds/{creds.url}
```

## Clusters API

### List Clusters

```
GET /api/v1/clusters
Query params: ?server=https://kubernetes.default.svc&name=in-cluster&id.type=string&id.value=string
```

### Get Cluster

```
GET /api/v1/clusters/{idValue}
Query params: ?id.type=name  // or "url"
```

### Create Cluster

```
POST /api/v1/clusters
Query params: ?upsert=true

Body:
{
  "server": "https://kubernetes.example.com:6443",
  "name": "production",
  "config": {
    "bearerToken": "string",
    "tlsClientConfig": {
      "insecure": false,
      "certData": "string",
      "keyData": "string",
      "caData": "string",
      "serverName": "string"
    },
    "awsAuthConfig": {
      "clusterName": "string",
      "roleARN": "string",
      "profile": "string"
    },
    "execProviderConfig": {
      "command": "string",
      "args": ["string"],
      "env": {"key": "value"},
      "apiVersion": "client.authentication.k8s.io/v1beta1",
      "installHint": "string"
    }
  },
  "namespaces": ["default", "kube-system"],
  "refreshRequestedAt": "2023-01-01T00:00:00Z",
  "shard": 0,
  "project": "default",
  "labels": {"environment": "production"},
  "annotations": {}
}
```

### Update Cluster

```
PUT /api/v1/clusters/{idValue}
Query params: ?id.type=name&updatedFields=config,namespaces

Body: Same as create
```

### Delete Cluster

```
DELETE /api/v1/clusters/{server}
Query params: ?name=string&id.type=url
```

### Rotate Cluster Auth

```
POST /api/v1/clusters/{idValue}/rotate-auth
Query params: ?id.type=name
```

### Invalidate Cluster Cache

```
POST /api/v1/clusters/{idValue}/invalidate-cache
Query params: ?id.type=name
```

## Account API

### List Accounts

```
GET /api/v1/account
```

### Get Account Info

```
GET /api/v1/account/{name}
```

### Update Password

```
PUT /api/v1/account/password

Body:
{
  "currentPassword": "string",
  "name": "admin",
  "newPassword": "string"
}
```

### Generate Token

```
POST /api/v1/account/{name}/token

Body:
{
  "expiresIn": 86400,  // Seconds
  "id": "token-identifier"
}
```

### Check Permissions

```
GET /api/v1/account/can-i/{resource}/{action}/{subresource}

Example: GET /api/v1/account/can-i/applications/sync/*
```

## Session API

### Create Session (Login)

```
POST /api/v1/session

Body:
{
  "username": "admin",
  "password": "secret"
}

Response:
{
  "token": "eyJhbGci..."
}
```

### Delete Session (Logout)

```
DELETE /api/v1/session
```

### Get User Info

```
GET /api/v1/session/userinfo

Response:
{
  "loggedIn": true,
  "username": "admin",
  "iss": "argocd",
  "groups": ["admins"]
}
```

## Settings API

### Get Settings

```
GET /api/v1/settings

Response: Contains URL, dexConfig, oidcConfig, appLabelKey, resourceOverrides, statusBadgeEnabled, etc.
```

### Get Plugins

```
GET /api/v1/settings/plugins
```

## Certificates API

### List Certificates

```
GET /api/v1/certificates
Query params: ?hostNamePattern=*.example.com&certType=https&certSubType=string
```

### Create Certificates

```
POST /api/v1/certificates

Body:
{
  "items": [
    {
      "serverName": "github.com",
      "certType": "https",
      "certData": "-----BEGIN CERTIFICATE-----\n...",
      "certSubType": "string"
    },
    {
      "serverName": "github.com",
      "certType": "ssh",
      "certData": "github.com ssh-rsa AAAA...",
      "certSubType": "ssh-rsa"
    }
  ]
}
```

### Delete Certificate

```
DELETE /api/v1/certificates
Query params: ?hostNamePattern=github.com&certType=https&certSubType=string
```

## GPG Keys API

### List GPG Keys

```
GET /api/v1/gpgkeys
Query params: ?keyID=string
```

### Create GPG Key

```
POST /api/v1/gpgkeys

Body:
{
  "publicKey": "-----BEGIN PGP PUBLIC KEY BLOCK-----\n..."
}
```

### Get GPG Key

```
GET /api/v1/gpgkeys/{keyID}
```

### Delete GPG Key

```
DELETE /api/v1/gpgkeys/{keyID}
```

## Notification API

### List Notification Services

```
GET /api/v1/notifications/services
```

### List Notification Templates

```
GET /api/v1/notifications/templates
```

### List Notification Triggers

```
GET /api/v1/notifications/triggers
```

## Version API

### Get Version

```
GET /api/version

Response:
{
  "Version": "v2.9.0",
  "BuildDate": "2023-10-01T00:00:00Z",
  "GitCommit": "abc123",
  "GitTreeState": "clean",
  "GoVersion": "go1.21.0",
  "Compiler": "gc",
  "Platform": "linux/amd64",
  "KustomizeVersion": "v5.1.0",
  "HelmVersion": "v3.12.0",
  "KubectlVersion": "v1.28.0",
  "JsonnetVersion": "v0.20.0"
}
```

## Error Response Format

```json
{
  "error": "permission denied: applications, sync, default/myapp, sub: admin, iat: 2023-01-01T00:00:00Z",
  "code": 7,
  "message": "permission denied"
}
```

Error codes:

- `5` - Not Found
- `7` - Permission Denied
- `16` - Unauthenticated
- `3` - Invalid Argument
- `6` - Already Exists
