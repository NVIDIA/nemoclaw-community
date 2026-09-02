# Cluster-Code Development Guidelines

**Purpose**: Provides comprehensive development patterns and best practices for contributing to the cluster-code project, a TypeScript-based CLI tool for Kubernetes/OpenShift cluster management with AI-powered capabilities.

**When to Use**: Activated when working on cluster-code source files, adding features, fixing bugs, or extending the CLI tool.

---

## Project Architecture Overview

### Core Technology Stack
- **Language**: TypeScript 5.3+ (strict mode enabled)
- **Runtime**: Node.js 18+
- **Build**: TSC compiler
- **Package Manager**: npm
- **CLI Framework**: Commander.js
- **AI SDK**: Vercel AI SDK (multi-provider support)
- **Styling**: Chalk for terminal colors, cli-table3 for tables, ora for spinners

### Directory Structure
```
cluster-code/
├── src/
│   ├── cli.ts              # CLI entry point
│   ├── index.ts            # Main exports
│   ├── chat/               # Interactive chat interface
│   ├── config/             # Configuration management
│   ├── llm/                # LLM provider integration
│   ├── utils/              # Utilities (kubectl, logger, etc.)
│   └── types/              # TypeScript type definitions
├── .claude/
│   ├── agents/             # Specialized AI agents
│   ├── commands/           # Slash commands
│   ├── skills/             # Development skills (this directory)
│   └── hooks/              # Automation hooks
├── plugins/                # Plugin system
├── bin/                    # Binary entry point
└── dist/                   # Compiled output
```

---

## TypeScript Development Standards

### 1. Type Safety
```typescript
// ✅ GOOD: Explicit types, no any
interface ClusterConfig {
  context: string;
  namespace: string;
  provider?: LLMProvider;
}

function initCluster(config: ClusterConfig): Promise<void> {
  // Implementation
}

// ❌ BAD: Using any
function initCluster(config: any): Promise<any> {
  // Avoid this
}
```

### 2. Strict Compiler Options
All code must comply with strict TypeScript settings:
- `strict: true`
- `noImplicitAny: true`
- `strictNullChecks: true`
- `noUnusedLocals: true`
- `noUnusedParameters: true`

### 3. Import/Export Patterns
```typescript
// ✅ GOOD: Named exports for better tree-shaking
export class KubectlClient {
  // Implementation
}

export function executeCommand(cmd: string): Promise<string> {
  // Implementation
}

// ❌ AVOID: Default exports (except for main entry points)
export default KubectlClient;
```

### 4. Error Handling
```typescript
// ✅ GOOD: Custom error types with context
class KubectlError extends Error {
  constructor(
    message: string,
    public readonly command: string,
    public readonly exitCode?: number
  ) {
    super(message);
    this.name = 'KubectlError';
  }
}

async function runKubectl(args: string[]): Promise<string> {
  try {
    const result = await executeKubectl(args);
    return result;
  } catch (error) {
    if (error instanceof Error) {
      throw new KubectlError(error.message, args.join(' '));
    }
    throw error;
  }
}
```

---

## CLI Development Patterns

### 1. Command Structure
```typescript
// Use Commander.js for consistent CLI interface
import { Command } from 'commander';

const program = new Command();

program
  .name('cluster-code')
  .description('AI-powered Kubernetes cluster management')
  .version('1.0.0');

// Add subcommands with clear descriptions
program
  .command('init')
  .description('Initialize cluster connection')
  .option('-c, --context <context>', 'Kubernetes context')
  .option('-n, --namespace <namespace>', 'Default namespace')
  .action(async (options) => {
    // Implementation
  });
```

### 2. User Interaction
```typescript
import inquirer from 'inquirer';
import ora from 'ora';
import chalk from 'chalk';

// ✅ GOOD: Interactive prompts for user input
async function promptForConfig(): Promise<ClusterConfig> {
  const answers = await inquirer.prompt([
    {
      type: 'list',
      name: 'context',
      message: 'Select Kubernetes context:',
      choices: await getKubeContexts(),
    },
    {
      type: 'input',
      name: 'namespace',
      message: 'Default namespace:',
      default: 'default',
    },
  ]);

  return answers;
}

// ✅ GOOD: Spinners for long-running operations
async function analyzeCluster(): Promise<void> {
  const spinner = ora('Analyzing cluster health...').start();

  try {
    const result = await performAnalysis();
    spinner.succeed('Analysis complete!');
    console.log(result);
  } catch (error) {
    spinner.fail('Analysis failed');
    throw error;
  }
}

// ✅ GOOD: Colored output for readability
console.log(chalk.green('✓'), 'Cluster connected successfully');
console.log(chalk.red('✗'), 'Failed to connect to cluster');
console.log(chalk.yellow('⚠'), 'Warning: High memory usage detected');
```

### 3. Configuration Management
```typescript
// Configuration files in ~/.cluster-code/
const CONFIG_DIR = path.join(os.homedir(), '.cluster-code');
const CONFIG_FILE = path.join(CONFIG_DIR, 'config.json');

// ✅ GOOD: Type-safe config with defaults
interface Config {
  llm: LLMConfig;
  cluster?: ClusterConfig;
  providers: Record<string, ProviderConfig>;
}

export class ConfigManager {
  private config: Config;

  constructor() {
    this.config = this.load();
  }

  private load(): Config {
    if (!fs.existsSync(CONFIG_FILE)) {
      return this.getDefaultConfig();
    }

    const data = fs.readFileSync(CONFIG_FILE, 'utf-8');
    return JSON.parse(data);
  }

  save(): void {
    fs.mkdirSync(CONFIG_DIR, { recursive: true });
    fs.writeFileSync(CONFIG_FILE, JSON.stringify(this.config, null, 2));
  }

  get<K extends keyof Config>(key: K): Config[K] {
    return this.config[key];
  }

  set<K extends keyof Config>(key: K, value: Config[K]): void {
    this.config[key] = value;
    this.save();
  }
}
```

---

## LLM Provider Integration

### 1. Multi-Provider Architecture
```typescript
// Use Vercel AI SDK for provider abstraction
import { createAnthropic } from '@ai-sdk/anthropic';
import { createOpenAI } from '@ai-sdk/openai';
import { createGoogleGenerativeAI } from '@ai-sdk/google';
import { generateText, streamText } from 'ai';

// ✅ GOOD: Provider factory pattern
export function createLLMProvider(config: ProviderConfig): LanguageModel {
  switch (config.type) {
    case 'anthropic':
      return createAnthropic({
        apiKey: config.apiKey,
      })(config.model || 'claude-3-5-sonnet-20241022');

    case 'openai':
      return createOpenAI({
        apiKey: config.apiKey,
      })(config.model || 'gpt-4');

    case 'google':
      return createGoogleGenerativeAI({
        apiKey: config.apiKey,
      })(config.model || 'gemini-1.5-pro');

    case 'ollama':
      return createOpenAI({
        baseURL: config.baseURL || 'http://localhost:11434/v1',
      })(config.model || 'llama3');

    default:
      throw new Error(`Unknown provider type: ${config.type}`);
  }
}
```

### 2. Streaming Responses
```typescript
// ✅ GOOD: Stream LLM responses for better UX
async function chatWithCluster(userMessage: string): Promise<void> {
  const provider = createLLMProvider(config.get('providers').active);

  const result = await streamText({
    model: provider,
    messages: [
      { role: 'system', content: SYSTEM_PROMPT },
      { role: 'user', content: userMessage },
    ],
    maxTokens: 4096,
  });

  process.stdout.write('\nAssistant: ');

  for await (const chunk of result.textStream) {
    process.stdout.write(chunk);
  }

  process.stdout.write('\n\n');
}
```

---

## Kubernetes Integration

### 1. kubectl Wrapper
```typescript
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

// ✅ GOOD: Type-safe kubectl wrapper
export class KubectlClient {
  constructor(
    private context?: string,
    private namespace?: string
  ) {}

  async execute(args: string[]): Promise<string> {
    const contextArg = this.context ? `--context=${this.context}` : '';
    const namespaceArg = this.namespace ? `--namespace=${this.namespace}` : '';

    const cmd = ['kubectl', contextArg, namespaceArg, ...args]
      .filter(Boolean)
      .join(' ');

    try {
      const { stdout, stderr } = await execAsync(cmd);
      if (stderr && !stderr.includes('Warning')) {
        console.warn(chalk.yellow(stderr));
      }
      return stdout;
    } catch (error) {
      throw new KubectlError(
        error instanceof Error ? error.message : String(error),
        cmd
      );
    }
  }

  async getPods(labels?: string): Promise<Pod[]> {
    const args = ['get', 'pods', '-o', 'json'];
    if (labels) {
      args.push('-l', labels);
    }

    const output = await this.execute(args);
    const data = JSON.parse(output);
    return data.items;
  }
}
```

### 2. Resource Type Definitions
```typescript
// Define K8s resource types for better type safety
interface Pod {
  metadata: {
    name: string;
    namespace: string;
    labels?: Record<string, string>;
  };
  spec: {
    containers: Container[];
    nodeSelector?: Record<string, string>;
  };
  status: {
    phase: 'Pending' | 'Running' | 'Succeeded' | 'Failed' | 'Unknown';
    conditions?: PodCondition[];
  };
}

interface Container {
  name: string;
  image: string;
  resources?: {
    requests?: Record<string, string>;
    limits?: Record<string, string>;
  };
}
```

---

## Plugin System

### 1. Plugin Structure
```typescript
// Plugin interface for extensibility
export interface ClusterCodePlugin {
  name: string;
  version: string;
  description: string;

  // Optional lifecycle hooks
  init?(): Promise<void>;
  destroy?(): Promise<void>;

  // Plugin capabilities
  commands?: PluginCommand[];
  agents?: PluginAgent[];
  analyzers?: PluginAnalyzer[];
}

export interface PluginCommand {
  name: string;
  description: string;
  execute(context: CommandContext): Promise<void>;
}
```

### 2. Plugin Loading
```typescript
// ✅ GOOD: Dynamic plugin loading
export class PluginManager {
  private plugins: Map<string, ClusterCodePlugin> = new Map();

  async loadPlugin(pluginPath: string): Promise<void> {
    try {
      const plugin = await import(pluginPath);

      if (!this.isValidPlugin(plugin)) {
        throw new Error(`Invalid plugin: ${pluginPath}`);
      }

      if (plugin.init) {
        await plugin.init();
      }

      this.plugins.set(plugin.name, plugin);
    } catch (error) {
      console.error(chalk.red(`Failed to load plugin: ${pluginPath}`), error);
    }
  }

  private isValidPlugin(plugin: any): plugin is ClusterCodePlugin {
    return (
      typeof plugin.name === 'string' &&
      typeof plugin.version === 'string' &&
      typeof plugin.description === 'string'
    );
  }
}
```

---

## Testing Standards

### 1. Unit Tests
```typescript
// Use Jest for testing
import { KubectlClient } from '../utils/kubectl';

describe('KubectlClient', () => {
  let client: KubectlClient;

  beforeEach(() => {
    client = new KubectlClient('test-context', 'default');
  });

  it('should execute kubectl command with context', async () => {
    // Mock exec
    jest.spyOn(client as any, 'execute').mockResolvedValue('{}');

    const result = await client.execute(['get', 'pods']);

    expect(result).toBe('{}');
  });

  it('should throw KubectlError on failure', async () => {
    jest.spyOn(client as any, 'execute').mockRejectedValue(
      new Error('Command failed')
    );

    await expect(client.getPods()).rejects.toThrow(KubectlError);
  });
});
```

### 2. Integration Tests
```typescript
// Test actual kubectl integration (requires cluster)
describe('KubectlClient Integration', () => {
  // Skip if no cluster available
  const skipIfNoCluster = process.env.SKIP_INTEGRATION_TESTS ? it.skip : it;

  skipIfNoCluster('should get pods from cluster', async () => {
    const client = new KubectlClient();
    const pods = await client.getPods();

    expect(Array.isArray(pods)).toBe(true);
  });
});
```

---

## Performance Optimization

### 1. Async/Await Best Practices
```typescript
// ✅ GOOD: Parallel execution when possible
async function analyzeCluster(): Promise<AnalysisResult> {
  const [pods, nodes, services] = await Promise.all([
    kubectl.getPods(),
    kubectl.getNodes(),
    kubectl.getServices(),
  ]);

  return {
    pods: analyzePods(pods),
    nodes: analyzeNodes(nodes),
    services: analyzeServices(services),
  };
}

// ❌ BAD: Sequential when parallel is possible
async function analyzeCluster(): Promise<AnalysisResult> {
  const pods = await kubectl.getPods();
  const nodes = await kubectl.getNodes();
  const services = await kubectl.getServices();

  return { /* ... */ };
}
```

### 2. Caching
```typescript
// ✅ GOOD: Cache expensive operations
class ClusterCache {
  private cache = new Map<string, { data: any; timestamp: number }>();
  private readonly TTL = 5 * 60 * 1000; // 5 minutes

  async get<T>(
    key: string,
    fetcher: () => Promise<T>
  ): Promise<T> {
    const cached = this.cache.get(key);

    if (cached && Date.now() - cached.timestamp < this.TTL) {
      return cached.data as T;
    }

    const data = await fetcher();
    this.cache.set(key, { data, timestamp: Date.now() });

    return data;
  }

  invalidate(key?: string): void {
    if (key) {
      this.cache.delete(key);
    } else {
      this.cache.clear();
    }
  }
}
```

---

## Security Best Practices

### 1. API Key Management
```typescript
// ✅ GOOD: Never commit API keys
// Use environment variables or secure config
function getAPIKey(provider: string): string {
  const envKey = `${provider.toUpperCase()}_API_KEY`;
  const key = process.env[envKey] || config.get('providers')[provider]?.apiKey;

  if (!key) {
    throw new Error(
      `API key not found for ${provider}. ` +
      `Set ${envKey} environment variable or run: ` +
      `cluster-code config provider add ${provider}`
    );
  }

  return key;
}
```

### 2. Input Validation
```typescript
// ✅ GOOD: Validate user input
function validateNamespace(namespace: string): void {
  if (!/^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/.test(namespace)) {
    throw new Error(
      'Invalid namespace. Must be lowercase alphanumeric with hyphens.'
    );
  }

  if (namespace.length > 63) {
    throw new Error('Namespace must be 63 characters or less');
  }
}
```

### 3. Command Injection Prevention
```typescript
// ✅ GOOD: Sanitize arguments
function sanitizeArg(arg: string): string {
  // Remove shell metacharacters
  return arg.replace(/[;&|`$()]/g, '');
}

// Better: Use array-based execution
async function execute(command: string, args: string[]): Promise<string> {
  // Use execFile instead of exec to avoid shell injection
  const { stdout } = await execFileAsync(command, args);
  return stdout;
}
```

---

## Code Organization Principles

### 1. Single Responsibility
```typescript
// ✅ GOOD: Each class/function has one purpose
class PodAnalyzer {
  analyze(pods: Pod[]): PodAnalysis {
    return {
      total: pods.length,
      byPhase: this.groupByPhase(pods),
      issues: this.detectIssues(pods),
    };
  }

  private groupByPhase(pods: Pod[]): Record<string, number> {
    // Implementation
  }

  private detectIssues(pods: Pod[]): Issue[] {
    // Implementation
  }
}

class PodFormatter {
  formatAsTable(analysis: PodAnalysis): string {
    // Table formatting logic
  }

  formatAsJSON(analysis: PodAnalysis): string {
    // JSON formatting logic
  }
}
```

### 2. Dependency Injection
```typescript
// ✅ GOOD: Inject dependencies for testability
class ClusterAnalyzer {
  constructor(
    private kubectl: KubectlClient,
    private llm: LanguageModel,
    private logger: Logger
  ) {}

  async analyze(): Promise<AnalysisResult> {
    const pods = await this.kubectl.getPods();
    const analysis = await this.llm.analyze(pods);
    this.logger.info('Analysis complete');
    return analysis;
  }
}

// Usage
const analyzer = new ClusterAnalyzer(
  new KubectlClient(),
  createLLMProvider(config),
  new Logger()
);
```

---

## Documentation Standards

### 1. JSDoc Comments
```typescript
/**
 * Analyzes cluster health and identifies potential issues.
 *
 * @param options - Analysis options
 * @param options.namespace - Namespace to analyze (optional, default: all)
 * @param options.deep - Perform deep analysis including logs (default: false)
 * @returns Analysis result with issues and recommendations
 * @throws {KubectlError} If cluster is unreachable
 *
 * @example
 * ```typescript
 * const result = await analyzeCluster({ namespace: 'production', deep: true });
 * console.log(result.issues);
 * ```
 */
export async function analyzeCluster(
  options: AnalysisOptions = {}
): Promise<AnalysisResult> {
  // Implementation
}
```

### 2. README Updates
When adding features, update:
- `README.md` - User-facing documentation
- `DEVELOPMENT.md` - Developer setup and contribution guide
- `CHANGELOG.md` - Version history with changes

---

## Git Workflow

### 1. Branch Naming
- Feature: `feature/add-eks-support`
- Bug fix: `fix/kubectl-timeout-error`
- Claude branches: `claude/description-sessionId`

### 2. Commit Messages
```
feat: add support for AWS EKS cluster provisioning

- Add EKS client with CloudFormation integration
- Implement cluster creation and deletion
- Add EKS-specific configuration options

Closes #42
```

### 3. Pull Requests
- Clear title and description
- Link related issues
- Include test results
- Update documentation

---

## Common Patterns

### 1. Table Output
```typescript
import Table from 'cli-table3';

function displayPods(pods: Pod[]): void {
  const table = new Table({
    head: ['NAME', 'STATUS', 'RESTARTS', 'AGE'],
    colWidths: [40, 15, 10, 15],
  });

  pods.forEach(pod => {
    table.push([
      pod.metadata.name,
      pod.status.phase,
      getRestartCount(pod),
      getAge(pod.metadata.creationTimestamp),
    ]);
  });

  console.log(table.toString());
}
```

### 2. Progress Bars
```typescript
import ora from 'ora';

async function provisionCluster(name: string): Promise<void> {
  const steps = [
    { name: 'Creating VPC', fn: createVPC },
    { name: 'Creating cluster', fn: createCluster },
    { name: 'Configuring access', fn: configureAccess },
  ];

  for (const step of steps) {
    const spinner = ora(step.name).start();
    try {
      await step.fn(name);
      spinner.succeed();
    } catch (error) {
      spinner.fail();
      throw error;
    }
  }
}
```

---

## Resources

- **TypeScript Handbook**: https://www.typescriptlang.org/docs/
- **Commander.js**: https://github.com/tj/commander.js
- **Vercel AI SDK**: https://sdk.vercel.ai/docs
- **Kubernetes API**: https://kubernetes.io/docs/reference/kubernetes-api/
- **Node.js Best Practices**: https://github.com/goldbergyoni/nodebestpractices

---

**Remember**: This is a CLI tool for DevOps/SRE teams. Focus on:
- Clear, informative output
- Robust error handling
- Fast performance
- Extensibility through plugins
- Excellent developer experience
