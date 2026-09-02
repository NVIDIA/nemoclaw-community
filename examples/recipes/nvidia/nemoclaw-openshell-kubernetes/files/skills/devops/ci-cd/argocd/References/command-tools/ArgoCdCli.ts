#!/usr/bin/env bun
/**
 * ArgoCdCli - ArgoCD CLI wrapper for example-app-hub cluster
 *
 * Usage:
 *   bun run ArgoCdCli.ts <command> [args...]
 *   bun run ArgoCdCli.ts --help
 *
 * Environment:
 *   ARGOCD_SERVER - ArgoCD server URL (default: argocd.example.com)
 *   ARGOCD_AUTH_TOKEN - Authentication token (optional)
 *   ARGOCD_INSECURE - Skip TLS verification (default: false)
 */

import { $ } from "bun";

// Configuration
const CONFIG = {
  servers: {
    production: "argocd.example.com",
    portforward: "localhost:8080",
  },
  defaultServer: process.env.ARGOCD_SERVER || "argocd.example.com",
  insecure: process.env.ARGOCD_INSECURE === "true",
  authToken: process.env.ARGOCD_AUTH_TOKEN,
  // example-app-hub cluster kubeconfig
  kubeconfig: process.env.KUBECONFIG || "~/.kube/aks-rg-example-hub-config",
  namespace: "argocd",
};

// Command categories
const COMMANDS = {
  auth: ["login", "logout", "relogin", "account"],
  app: ["app"],
  appset: ["appset"],
  cluster: ["cluster"],
  repo: ["repo", "repocreds"],
  project: ["proj"],
  admin: ["admin", "cert", "gpg"],
  util: ["version", "context", "configure", "completion"],
} as const;

interface CommandResult {
  success: boolean;
  output: string;
  error?: string;
}

/**
 * Check if argocd CLI is installed
 */
async function checkArgoCdInstalled(): Promise<boolean> {
  try {
    await $`which argocd`.quiet();
    return true;
  } catch {
    return false;
  }
}

/**
 * Check if logged in to ArgoCD
 */
async function checkLoggedIn(): Promise<boolean> {
  try {
    await $`argocd account get-user-info`.quiet();
    return true;
  } catch {
    return false;
  }
}

/**
 * Get current ArgoCD context
 */
async function getCurrentContext(): Promise<string | null> {
  try {
    const result = await $`argocd context`.text();
    const lines = result.trim().split("\n");
    for (const line of lines) {
      if (line.startsWith("*")) {
        return line.split(/\s+/)[1];
      }
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Execute argocd command
 */
async function executeCommand(args: string[]): Promise<CommandResult> {
  try {
    const result = await $`argocd ${args}`.text();
    return { success: true, output: result };
  } catch (error: any) {
    return {
      success: false,
      output: "",
      error: error.stderr?.toString() || error.message,
    };
  }
}

/**
 * Login to ArgoCD server
 */
async function login(server: string, options: { sso?: boolean; insecure?: boolean } = {}): Promise<CommandResult> {
  const args = ["login", server];

  if (options.sso) {
    args.push("--sso");
  }

  if (options.insecure || CONFIG.insecure) {
    args.push("--insecure");
  }

  if (CONFIG.authToken) {
    args.push("--auth-token", CONFIG.authToken);
  }

  return executeCommand(args);
}

/**
 * App management commands
 */
const app = {
  list: (options: { project?: string; selector?: string } = {}) => {
    const args = ["app", "list"];
    if (options.project) args.push("-p", options.project);
    if (options.selector) args.push("-l", options.selector);
    return executeCommand(args);
  },

  get: (name: string, options: { output?: string } = {}) => {
    const args = ["app", "get", name];
    if (options.output) args.push("-o", options.output);
    return executeCommand(args);
  },

  sync: (name: string, options: { prune?: boolean; force?: boolean; dryRun?: boolean } = {}) => {
    const args = ["app", "sync", name];
    if (options.prune) args.push("--prune");
    if (options.force) args.push("--force");
    if (options.dryRun) args.push("--dry-run");
    return executeCommand(args);
  },

  create: (name: string, options: {
    repo: string;
    path: string;
    dest_server: string;
    dest_namespace: string;
    project?: string;
  }) => {
    const args = [
      "app", "create", name,
      "--repo", options.repo,
      "--path", options.path,
      "--dest-server", options.dest_server,
      "--dest-namespace", options.dest_namespace,
    ];
    if (options.project) args.push("--project", options.project);
    return executeCommand(args);
  },

  delete: (name: string, options: { cascade?: boolean } = {}) => {
    const args = ["app", "delete", name, "--yes"];
    if (options.cascade === false) args.push("--cascade=false");
    return executeCommand(args);
  },

  diff: (name: string) => executeCommand(["app", "diff", name]),

  history: (name: string) => executeCommand(["app", "history", name]),

  rollback: (name: string, revisionId: number) =>
    executeCommand(["app", "rollback", name, String(revisionId)]),

  logs: (name: string, options: { follow?: boolean; container?: string } = {}) => {
    const args = ["app", "logs", name];
    if (options.follow) args.push("--follow");
    if (options.container) args.push("-c", options.container);
    return executeCommand(args);
  },

  resources: (name: string) => executeCommand(["app", "resources", name]),

  wait: (name: string, options: { health?: boolean; sync?: boolean; timeout?: number } = {}) => {
    const args = ["app", "wait", name];
    if (options.health) args.push("--health");
    if (options.sync) args.push("--sync");
    if (options.timeout) args.push("--timeout", String(options.timeout));
    return executeCommand(args);
  },
};

/**
 * ApplicationSet management commands
 */
const appset = {
  list: (options: { project?: string; selector?: string } = {}) => {
    const args = ["appset", "list"];
    if (options.project) args.push("-p", options.project);
    if (options.selector) args.push("-l", options.selector);
    return executeCommand(args);
  },

  get: (name: string, options: { output?: string } = {}) => {
    const args = ["appset", "get", name];
    if (options.output) args.push("-o", options.output);
    return executeCommand(args);
  },

  create: (file: string, options: { upsert?: boolean; dryRun?: boolean } = {}) => {
    const args = ["appset", "create", "-f", file];
    if (options.upsert) args.push("--upsert");
    if (options.dryRun) args.push("--dry-run");
    return executeCommand(args);
  },

  delete: (name: string) => executeCommand(["appset", "delete", name, "--yes"]),

  generate: (file: string) => executeCommand(["appset", "generate", file]),
};

/**
 * Cluster management commands
 */
const cluster = {
  list: () => executeCommand(["cluster", "list"]),

  get: (server: string, options: { output?: string } = {}) => {
    const args = ["cluster", "get", server];
    if (options.output) args.push("-o", options.output);
    return executeCommand(args);
  },

  add: (context: string, options: { name?: string; inCluster?: boolean } = {}) => {
    const args = ["cluster", "add", context];
    if (options.name) args.push("--name", options.name);
    if (options.inCluster) args.push("--in-cluster");
    return executeCommand(args);
  },

  rm: (server: string) => executeCommand(["cluster", "rm", server]),

  rotateAuth: (server: string) => executeCommand(["cluster", "rotate-auth", server]),
};

/**
 * Repository management commands
 */
const repo = {
  list: () => executeCommand(["repo", "list"]),

  get: (url: string) => executeCommand(["repo", "get", url]),

  add: (url: string, options: {
    type?: "git" | "helm" | "oci";
    name?: string;
    username?: string;
    password?: string;
    sshPrivateKeyPath?: string;
  } = {}) => {
    const args = ["repo", "add", url];
    if (options.type) args.push("--type", options.type);
    if (options.name) args.push("--name", options.name);
    if (options.username) args.push("--username", options.username);
    if (options.password) args.push("--password", options.password);
    if (options.sshPrivateKeyPath) args.push("--ssh-private-key-path", options.sshPrivateKeyPath);
    return executeCommand(args);
  },

  rm: (url: string) => executeCommand(["repo", "rm", url]),
};

/**
 * Project management commands
 */
const proj = {
  list: () => executeCommand(["proj", "list"]),

  get: (name: string, options: { output?: string } = {}) => {
    const args = ["proj", "get", name];
    if (options.output) args.push("-o", options.output);
    return executeCommand(args);
  },

  create: (name: string, options: { description?: string; destServer?: string; destNamespace?: string } = {}) => {
    const args = ["proj", "create", name];
    if (options.description) args.push("--description", options.description);
    if (options.destServer) args.push("-d", `${options.destServer},${options.destNamespace || "*"}`);
    return executeCommand(args);
  },

  delete: (name: string) => executeCommand(["proj", "delete", name]),

  addSource: (name: string, url: string) => executeCommand(["proj", "add-source", name, url]),

  removeSource: (name: string, url: string) => executeCommand(["proj", "remove-source", name, url]),

  addDestination: (name: string, server: string, namespace: string) =>
    executeCommand(["proj", "add-destination", name, server, namespace]),

  removeDestination: (name: string, server: string, namespace: string) =>
    executeCommand(["proj", "remove-destination", name, server, namespace]),
};

/**
 * Print help
 */
function printHelp(): void {
  console.log(`
ArgoCdCli - ArgoCD CLI wrapper for example-app-hub cluster

USAGE:
  bun run ArgoCdCli.ts <command> [subcommand] [args...]
  bun run ArgoCdCli.ts --help

SERVERS:
  Production:   argocd.example.com
  Port-Forward: localhost:8080

COMMANDS:
  login [server]              Login to ArgoCD (default: ${CONFIG.defaultServer})
  logout                      Logout from ArgoCD

  app list                    List all applications
  app get <name>              Get application details
  app sync <name>             Sync application
  app diff <name>             Show diff between target and live state
  app logs <name>             Get application pod logs
  app history <name>          Show deployment history
  app rollback <name> <id>    Rollback to revision
  app delete <name>           Delete application

  appset list                 List all ApplicationSets
  appset get <name>           Get ApplicationSet details
  appset create -f <file>     Create ApplicationSet from file
  appset delete <name>        Delete ApplicationSet
  appset generate <file>      Generate apps from ApplicationSet

  cluster list                List registered clusters
  cluster get <server>        Get cluster details
  cluster add <context>       Add cluster from kubeconfig context
  cluster rm <server>         Remove cluster

  repo list                   List configured repositories
  repo get <url>              Get repository details
  repo add <url>              Add repository
  repo rm <url>               Remove repository

  proj list                   List projects
  proj get <name>             Get project details
  proj create <name>          Create project
  proj delete <name>          Delete project

OPTIONS:
  --help, -h                  Show this help message
  --output, -o <format>       Output format (json, yaml, wide)
  --insecure                  Skip TLS verification
  --sso                       Use SSO for login

ENVIRONMENT:
  ARGOCD_SERVER               Default server URL
  ARGOCD_AUTH_TOKEN           Authentication token
  ARGOCD_INSECURE             Skip TLS verification (true/false)

EXAMPLES:
  # Login to production
  bun run ArgoCdCli.ts login argocd.example.com --sso

  # Login via port-forward (example-app-hub cluster)
  kubectl --kubeconfig ~/.kube/aks-rg-example-hub-config port-forward svc/argocd-server -n argocd 8080:443 &
  bun run ArgoCdCli.ts login localhost:8080 --insecure

  # Sync application
  bun run ArgoCdCli.ts app sync grafana

  # Get app status as JSON
  bun run ArgoCdCli.ts app get defectdojo -o json

  # List ApplicationSets
  bun run ArgoCdCli.ts appset list
`);
}

/**
 * Main CLI handler
 */
async function main(): Promise<void> {
  const args = process.argv.slice(2);

  if (args.length === 0 || args.includes("--help") || args.includes("-h")) {
    printHelp();
    process.exit(0);
  }

  // Check argocd is installed
  if (!(await checkArgoCdInstalled())) {
    console.error("Error: argocd CLI is not installed");
    console.error("Install: https://argo-cd.readthedocs.io/en/stable/cli_installation/");
    process.exit(1);
  }

  // Pass through to argocd directly
  const result = await executeCommand(args);

  if (result.success) {
    console.log(result.output);
  } else {
    console.error(result.error);
    process.exit(1);
  }
}

// Export for programmatic use
export {
  CONFIG,
  login,
  app,
  appset,
  cluster,
  repo,
  proj,
  executeCommand,
  checkLoggedIn,
  getCurrentContext,
};

// Run CLI
main();
