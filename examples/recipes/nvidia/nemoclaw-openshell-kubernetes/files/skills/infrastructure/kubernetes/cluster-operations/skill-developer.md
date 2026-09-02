# Skill Developer

**Purpose**: Meta-skill for creating new Claude Code skills for the cluster-code project. This skill guides you through the process of designing, writing, and integrating custom skills into the .claude/skills/ directory.

**When to Use**: When you need to create a new skill to capture domain-specific knowledge, development patterns, or specialized workflows for cluster-code.

---

## What Are Skills?

Skills are markdown files that Claude Code can load to provide specialized knowledge and capabilities. They serve as:

- **Knowledge Repositories**: Domain-specific expertise (e.g., Kubernetes troubleshooting patterns)
- **Development Guidelines**: Best practices and coding standards (e.g., cluster-dev-guidelines)
- **Workflow Templates**: Step-by-step procedures for common tasks
- **Context Enhancers**: Additional information to improve AI assistance quality

---

## Skill Anatomy

### 1. Basic Structure

Every skill should follow this template:

```markdown
# Skill Name

**Purpose**: One-sentence description of what this skill provides

**When to Use**: Conditions that trigger or require this skill

---

## Section 1: Core Content

Main content organized in logical sections...

---

## Section 2: Examples

Practical examples demonstrating the concepts...

---

## Resources

Links to documentation, tools, or references
```

### 2. Key Components

**Header (Required)**
- Clear, descriptive title
- Purpose statement (what this skill provides)
- When to Use (activation conditions)

**Content Sections (Required)**
- Organized by topic or workflow stage
- Use markdown formatting (headings, code blocks, lists)
- Include both explanation and examples

**Code Examples (Recommended)**
- Use syntax-highlighted code blocks
- Show both good (✅) and bad (❌) examples
- Include inline comments for clarity

**Resources (Optional)**
- External documentation links
- Related tools or libraries
- Further reading materials

---

## Skill Design Principles

### 1. Single Responsibility
Each skill should focus on ONE domain or topic:

✅ **GOOD**:
- `k8s-troubleshooting.md` - Kubernetes-specific debugging patterns
- `plugin-development.md` - Guide for creating cluster-code plugins

❌ **BAD**:
- `everything-kubernetes.md` - Too broad, unfocused

### 2. Progressive Disclosure
Keep the main file under 500 lines. For larger topics, use the resource pattern:

```markdown
# Main Skill File (300 lines)

## Advanced Topics

For detailed information, see:
- [Advanced Patterns](./resources/advanced-patterns.md)
- [API Reference](./resources/api-reference.md)
```

Create a `resources/` subdirectory for supplementary content.

### 3. Practical Examples
Every concept should have a code example:

```typescript
// ✅ GOOD: Show the pattern
export class ClusterHealthChecker {
  async check(): Promise<HealthStatus> {
    const nodes = await this.kubectl.getNodes();
    return this.analyzeNodes(nodes);
  }
}

// ❌ BAD: Avoid this anti-pattern
export class God {
  doEverything() {
    // Too much responsibility
  }
}
```

### 4. Context-Aware Content
Tailor content to cluster-code's tech stack:
- TypeScript/Node.js patterns
- kubectl/Kubernetes integration
- CLI tool development
- LLM provider patterns

---

## Creating a New Skill

### Step 1: Identify the Need

Ask yourself:
- What knowledge gap does this fill?
- What tasks would this skill help with?
- Is this topic broad enough to warrant a skill?

**Good skill topics for cluster-code**:
- `k8s-troubleshooting.md` - Kubernetes debugging patterns
- `plugin-development.md` - Plugin creation guide
- `llm-integration.md` - Adding new LLM providers
- `operator-testing.md` - OpenShift operator testing
- `multi-cloud-patterns.md` - Cloud provider integration

### Step 2: Outline the Structure

Create a content outline:

```markdown
# [Skill Name]

**Purpose**: [One sentence]
**When to Use**: [Activation conditions]

---

## Overview
- What this skill covers
- Prerequisites

## Core Concepts
- Concept 1
- Concept 2
- Concept 3

## Practical Examples
- Example 1
- Example 2

## Best Practices
- Practice 1
- Practice 2

## Common Pitfalls
- Pitfall 1 (and how to avoid it)

## Resources
- Links and references
```

### Step 3: Write the Content

Follow these guidelines:

**Use Clear Headings**
```markdown
## Main Topic (Level 2)

### Subtopic (Level 3)

#### Detail (Level 4)
```

**Format Code Consistently**
```typescript
// Use TypeScript for cluster-code examples
interface Example {
  property: string;
}

function demonstrate(example: Example): void {
  console.log(example.property);
}
```

**Add Visual Indicators**
```markdown
✅ **GOOD**: Recommended approach
❌ **BAD**: Avoid this pattern
⚠️ **WARNING**: Important caveat
💡 **TIP**: Helpful insight
```

**Include Realistic Examples**
Use cluster-code domain examples:
```typescript
// ✅ GOOD: Relevant to cluster-code
const kubectl = new KubectlClient('prod-cluster', 'monitoring');
const pods = await kubectl.getPods('app=prometheus');

// ❌ AVOID: Generic unrelated examples
const users = await db.query('SELECT * FROM users');
```

### Step 4: Test the Skill

Before finalizing:

1. **Check Length**: Is it under 500 lines? If not, split into main + resources
2. **Test Examples**: Do code examples compile and run?
3. **Verify Links**: Are external links valid?
4. **Review Clarity**: Is it clear and actionable?

### Step 5: Integrate with Auto-Activation

Add an entry to `.claude/skill-rules.json`:

```json
{
  "skills": [
    {
      "name": "k8s-troubleshooting",
      "description": "Kubernetes troubleshooting patterns and diagnostics",
      "pathPatterns": [
        "src/utils/kubectl.ts",
        "src/analyzers/**/*.ts",
        ".claude/agents/pod-doctor.md",
        ".claude/agents/network-inspector.md"
      ],
      "keywords": [
        "pod",
        "deployment",
        "troubleshoot",
        "debug",
        "kubectl",
        "kubernetes",
        "failing",
        "crash"
      ]
    }
  ]
}
```

---

## Skill Templates

### Template 1: Development Guidelines

Use for coding standards and best practices:

```markdown
# [Technology/Domain] Development Guidelines

**Purpose**: Provides [specific patterns] for [use case]
**When to Use**: When working on [file types/features]

---

## Technology Stack Overview
- Key technologies
- Version requirements

## Code Standards
### Pattern 1
[Description]
[Example]

### Pattern 2
[Description]
[Example]

## Best Practices
1. Practice 1
2. Practice 2

## Common Pitfalls
- Pitfall and solution

## Resources
- Links
```

### Template 2: Troubleshooting Guide

Use for debugging and problem-solving:

```markdown
# [Domain] Troubleshooting Guide

**Purpose**: Diagnostic patterns for [specific problems]
**When to Use**: When encountering [error types]

---

## Common Issues

### Issue 1: [Problem Name]

**Symptoms**:
- Symptom 1
- Symptom 2

**Diagnosis**:
```bash
# Commands to run
kubectl get pods
```

**Solution**:
```bash
# Fix commands
kubectl rollout restart deployment/app
```

### Issue 2: [Problem Name]
[Same structure]

## Prevention
- How to avoid these issues

## Resources
- Documentation links
```

### Template 3: Feature Development

Use for adding new capabilities:

```markdown
# [Feature] Development Guide

**Purpose**: Guide for implementing [feature type]
**When to Use**: When adding [specific features]

---

## Architecture Overview
- How this feature fits into cluster-code

## Implementation Steps

### Step 1: [Action]
[Details and code]

### Step 2: [Action]
[Details and code]

## Testing
- Unit tests
- Integration tests

## Examples
- Real-world usage examples

## Resources
- Related documentation
```

---

## Skill Naming Conventions

Use clear, descriptive names:

✅ **GOOD**:
- `cluster-dev-guidelines.md` - Clear and specific
- `k8s-troubleshooting.md` - Domain-focused
- `plugin-development.md` - Task-focused

❌ **AVOID**:
- `stuff.md` - Too vague
- `everything.md` - Too broad
- `notes.md` - Not descriptive

---

## Organizing Multiple Skills

### Directory Structure

```
.claude/
└── skills/
    ├── cluster-dev-guidelines.md        # Core development patterns
    ├── skill-developer.md               # This meta-skill
    ├── k8s-troubleshooting.md          # Kubernetes debugging
    ├── plugin-development.md           # Plugin creation
    ├── llm-integration.md              # LLM provider patterns
    └── resources/                      # Shared resources
        ├── kubernetes-api-reference.md
        └── common-patterns.md
```

### Skill Relationships

Skills can reference each other:

```markdown
# Plugin Development

For TypeScript coding standards, see [Cluster Dev Guidelines](./cluster-dev-guidelines.md).

For testing your plugin with real clusters, see [K8s Troubleshooting](./k8s-troubleshooting.md).
```

---

## Auto-Activation Rules

Configure when skills automatically activate:

### Path Patterns
```json
{
  "pathPatterns": [
    "src/**/*.ts",           // All TypeScript files
    "plugins/**/index.ts",   // Plugin entry points
    ".claude/agents/*.md"    // Agent definitions
  ]
}
```

### Keywords
```json
{
  "keywords": [
    "kubernetes",
    "kubectl",
    "deployment",
    "troubleshoot"
  ]
}
```

When user prompts contain these keywords OR they're editing matching files, the skill auto-activates.

---

## Maintenance Guidelines

### Regular Updates
- Keep examples current with latest TypeScript/Node.js versions
- Update external links (quarterly)
- Add new patterns as they emerge

### Version Control
- Commit skills with descriptive messages
- Document major changes in comments
- Use git for tracking evolution

### Feedback Loop
- Note which skills are most/least used
- Gather feedback from the team
- Refine based on actual usage

---

## Advanced Patterns

### 1. Conditional Content

Include environment-specific content:

```markdown
## Cloud Provider Integration

### AWS EKS
[AWS-specific content]

### Azure AKS
[Azure-specific content]

### Google GKE
[GCP-specific content]

**Note**: Only relevant if working with the respective cloud provider plugin.
```

### 2. Code Snippets Library

Create reusable snippets:

```markdown
## Common Kubectl Patterns

### Get Pod Logs with Context
```typescript
async function getPodsWithLogs(namespace: string): Promise<PodWithLogs[]> {
  const kubectl = new KubectlClient(undefined, namespace);
  const pods = await kubectl.getPods();

  return await Promise.all(
    pods.map(async (pod) => ({
      pod,
      logs: await kubectl.getLogs(pod.metadata.name),
    }))
  );
}
```
```

### 3. Troubleshooting Decision Trees

Guide through complex diagnostics:

```markdown
## Debugging Pod Failures

1. Check pod status:
   - If `Pending`: Check node resources (go to section A)
   - If `CrashLoopBackOff`: Check logs (go to section B)
   - If `ImagePullBackOff`: Check image name (go to section C)

### Section A: Node Resources
[Content]

### Section B: Application Logs
[Content]

### Section C: Image Issues
[Content]
```

---

## Examples of Good Skills

### Example 1: Focused and Practical

```markdown
# OpenShift Operator Development

**Purpose**: Patterns for developing and testing OpenShift operators within cluster-code
**When to Use**: When working on operator-related plugins or features

---

## Operator Basics

OpenShift operators extend Kubernetes with custom controllers.

### Creating an Operator Plugin

```typescript
export class OperatorPlugin implements ClusterCodePlugin {
  name = 'my-operator';

  async init(): Promise<void> {
    // Register custom resources
    await this.registerCRDs();
  }

  private async registerCRDs(): Promise<void> {
    const kubectl = new KubectlClient();
    await kubectl.apply('crds/my-crd.yaml');
  }
}
```

[More content...]
```

### Example 2: Comprehensive but Organized

```markdown
# Multi-Cloud Cluster Provisioning

**Purpose**: Patterns for provisioning clusters across AWS, Azure, and GCP
**When to Use**: When implementing cloud provider integrations

---

## Table of Contents
1. [Architecture Overview](#architecture)
2. [AWS EKS](#aws-eks)
3. [Azure AKS](#azure-aks)
4. [Google GKE](#google-gke)
5. [Common Patterns](#common-patterns)

[Each section is detailed but focused...]
```

---

## Skill Checklist

Before finalizing a skill, verify:

- [ ] Clear title and purpose statement
- [ ] "When to Use" section explains activation
- [ ] Content organized with logical headings
- [ ] Code examples are tested and correct
- [ ] Examples use cluster-code domain context
- [ ] Good (✅) and bad (❌) examples included
- [ ] File is under 500 lines (or split into resources)
- [ ] External links are valid
- [ ] Added to skill-rules.json for auto-activation
- [ ] Committed to git with descriptive message

---

## Getting Help

If you're unsure about skill design:

1. Review existing skills in `.claude/skills/`
2. Check the [Claude Code documentation](https://docs.claude.com)
3. Look at similar skills in other Claude Code projects
4. Start simple and iterate based on usage

---

## Resources

- **Markdown Guide**: https://www.markdownguide.org/
- **Claude Code Skills Docs**: https://docs.claude.com/docs/claude-code/skills
- **cluster-code Architecture**: See `CLUSTER_CODE_IMPLEMENTATION.md`
- **Existing Skills**: Browse `.claude/skills/` for examples

---

**Remember**: Skills are living documents. Start with the essentials, use them in practice, and refine based on real-world usage. The best skills evolve over time to meet actual needs.
