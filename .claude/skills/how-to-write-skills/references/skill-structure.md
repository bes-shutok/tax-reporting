# Skill Structure Guide

Complete guide to organizing your Claude Code Skills for maximum effectiveness and maintainability.

## Directory Organization Patterns

### Minimal Structure (Small Skills)

```
skill-name/
└── SKILL.md
```

**Use when**: Your guidance fits in < 300 lines and is focused on a single topic.

**Examples**:
- Simple utility helpers
- Single-purpose formatting rules
- Focused coding standards

### Standard Structure (Medium Skills)

```
skill-name/
├── SKILL.md              # Core instructions (200-400 lines)
└── references/           # Detailed documentation
    ├── topic-a.md        # Deep dive on aspect A
    └── topic-b.md        # Deep dive on aspect B
```

**Use when**: You need both quick reference and detailed explanations.

**Examples**:
- Domain-specific frameworks
- Multi-step workflows
- API design patterns

### Comprehensive Structure (Large Skills)

```
skill-name/
├── SKILL.md              # Essentials (300-500 lines)
├── references/           # Detailed docs
│   ├── architecture.md   # System architecture
│   ├── implementation.md # Implementation details
│   ├── patterns.md       # Design patterns
│   └── edge-cases.md     # Edge case handling
└── assets/              # Templates and examples
    ├── template.md       # Code template
    ├── checklist.md      # Verification checklist
    └── examples.md       # Real-world examples
```

**Use when**: Covering extensive topics that require progressive disclosure.

**Examples**:
- Complete framework guides
- Comprehensive testing strategies
- Complex development workflows

### Advanced Structure (Scripts and Templates)

```
skill-name/
├── SKILL.md              # Main skill
├── references/           # Documentation
│   └── guide.md
├── assets/              # Static assets
│   ├── templates/       # Code templates
│   │   ├── basic.py
│   │   └── advanced.py
│   └── examples/        # Usage examples
│       └── real-world.md
└── scripts/             # Executable scripts
    ├── generate.py      # Code generation
    └── validate.py      # Validation tool
```

**Use when**: Skill needs executable components or multiple template types.

## File Naming Conventions

### Main File
- **Always**: `SKILL.md` (uppercase)
- **Location**: Root of skill directory
- **Required**: Yes

### Reference Files
- **Format**: `kebab-case.md` (lowercase with hyphens)
- **Examples**:
  - ✅ `api-patterns.md`
  - ✅ `error-handling.md`
  - ✅ `best-practices.md`
  - ❌ `API_Patterns.md` (no underscores or caps)
  - ❌ `api patterns.md` (no spaces)

### Asset Files
- **Format**: `kebab-case.md` or with appropriate extensions
- **Examples**:
  - ✅ `template.py`
  - ✅ `checklist.md`
  - ✅ `example-config.yaml`
  - ❌ `myTemplate.py` (no camelCase)

### Script Files
- **Format**: Use appropriate extension for language
- **Examples**:
  - ✅ `generate.py`
  - ✅ `build.sh`
  - ✅ `transform.js`

## When to Use Subdirectories

### templates/ Subdirectory

Create when you have multiple code templates:

```
assets/
├── templates/
│   ├── python/
│   │   ├── basic.py
│   │   └── advanced.py
│   └── javascript/
│       ├── basic.js
│       └── advanced.js
└── examples.md
```

### examples/ Subdirectory

Create when you have many example files:

```
assets/
├── examples/
│   ├── simple-case.md
│   ├── complex-case.md
│   └── edge-cases.md
└── template.md
```

### scripts/ Subdirectory

Create when skill includes executable tools:

```
scripts/
├── setup.sh              # Setup automation
├── generate.py           # Code generation
├── validate.py           # Validation tool
└── transform.py          # Data transformation
```

**Note**: Scripts should be executable and well-documented.

## File Content Guidelines

### SKILL.md Structure

```markdown
---
name: skill-name
description: What it does + When to use it
---

# Skill Name

Brief overview...

## Quick Start
Immediate value...

## Core Principles
Essential concepts...

## When to Use This Skill
Specific scenarios...

## Common Patterns
Frequently used approaches...

## Additional Resources
Links to references/assets...
```

### Reference File Structure

```markdown
# [Topic Name]

Detailed explanation of a specific topic.

## Background
Context and history...

## Implementation
Step-by-step guide...

## Examples
Real-world usage...

## See Also
Related references...
```

### Asset File Structure

**Templates** (template.md, template.py, etc.):
```python
# Template for [purpose]
# Usage: [how to use]

def template_function():
    # Implementation
    pass
```

**Checklists** (checklist.md):
```markdown
# [Process] Checklist

## Pre-Conditions
- [ ] Check 1
- [ ] Check 2

## Process
- [ ] Step 1
- [ ] Step 2

## Post-Conditions
- [ ] Verify 1
- [ ] Verify 2
```

## Organizing by Skill Type

### Utility Skills

Simple, focused helpers.

```
formatter-skill/
└── SKILL.md
```

**Characteristics**:
- Single purpose
- Straightforward logic
- No complex examples

### Pattern Skills

Design patterns and best practices.

```
api-patterns/
├── SKILL.md
└── references/
    ├── rest-patterns.md
    ├── graphql-patterns.md
    └── examples.md
```

**Characteristics**:
- Multiple related patterns
- Need for examples
- Context-specific guidance

### Framework Skills

Comprehensive framework guides.

```
framework-guide/
├── SKILL.md
├── references/
│   ├── architecture.md
│   ├── components.md
│   ├── data-flow.md
│   └── security.md
└── assets/
    ├── templates/
    │   └── component.py
    └── checklists/
        └── review.md
```

**Characteristics**:
- Multiple interconnected concepts
- Architecture documentation
- Security considerations
- Template components

### Workflow Skills

Multi-step process guides.

```
workflow-skill/
├── SKILL.md
├── references/
│   ├── step-by-step.md
│   ├── decisions.md      # Decision points
│   └── troubleshooting.md
└── assets/
    ├── workflow-diagram.md
    └── checklist.md
```

**Characteristics**:
- Sequential processes
- Decision trees
- Error handling
- Progress tracking

## Directory Layout Examples

### Example 1: Testing Skill (Medium)

```
testing-patterns/
├── SKILL.md                    # 350 lines - core testing guidance
└── references/
    ├── unit-testing.md         # TDD, pytest patterns
    ├── integration-testing.md  # API testing, contracts
    ├── e2e-testing.md          # Full workflow tests
    └── mocking.md              # Test doubles, fixtures
```

### Example 2: API Design Skill (Large)

```
api-design/
├── SKILL.md                    # 450 lines - essentials
├── references/
│   ├── rest-principles.md      # REST fundamentals
│   ├── graphql-schema.md       # GraphQL patterns
│   ├── versioning.md           # API versioning strategies
│   ├── security.md             # Auth, rate limiting
│   └── documentation.md        # OpenAPI, docs
└── assets/
    ├── templates/
    │   ├── rest-api.py         # FastAPI template
    │   └── graphql-schema.graphql
    └── checklists/
        └── api-review.md       # Pre-merge checklist
```

### Example 3: Performance Skill (Complex)

```
performance-guide/
├── SKILL.md                    # 500 lines - optimization essentials
├── references/
│   ├── profiling.md            # cProfile, memory profilers
│   ├── database.md             # Query optimization
│   ├── caching.md              # Redis, memoization
│   ├── async.md                # asyncio, concurrency
│   └── monitoring.md           # APM, metrics
├── assets/
│   ├── scripts/
│   │   ├── profile.py          # Profiling wrapper
│   │   └── benchmark.py        # Benchmark runner
│   └── templates/
│       └── fast-query.sql      # Optimized query template
└── examples/
    ├── before-after/           # Optimization examples
    │   ├── slow.py
    │   └── fast.py
    └── case-studies.md
```

## Best Practices

### DO:
- ✅ Keep structure simple when possible
- ✅ Use descriptive file names
- ✅ Group related content together
- ✅ Maintain consistent organization
- ✅ Document complex directory structures
- ✅ Use subdirectories when > 5 files of same type

### DON'T:
- ❌ Create deep nesting (> 3 levels)
- ❌ Mix file types randomly
- ❌ Use cryptic abbreviations
- ❌ Duplicate directory structures
- ❌ Ignore patterns from existing skills

## Migration Patterns

### Growing from Small to Medium

**When**: SKILL.md exceeds 300 lines

**Action**: Extract details to references/

```
# Before
my-skill/
└── SKILL.md (450 lines)

# After
my-skill/
├── SKILL.md (280 lines) - essentials
└── references/
    ├── details.md (170 lines) - extracted
```

### Growing from Medium to Large

**When**: References/ exceeds 5 files or 1000 lines

**Action**: Add assets/ for templates/examples

```
# Before
my-skill/
├── SKILL.md
└── references/
    ├── guide.md (400 lines)
    ├── examples.md (300 lines)
    └── patterns.md (200 lines)

# After
my-skill/
├── SKILL.md
├── references/
│   ├── guide.md (400 lines)
│   └── patterns.md (200 lines)
└── assets/
    ├── template.md (100 lines)
    └── examples.md (300 lines)
```

## File Size Guidelines

| File Type | Target Size | Maximum |
|-----------|-------------|---------|
| SKILL.md | 200-400 lines | 600 lines |
| Reference | 100-300 lines | 500 lines |
| Asset Template | 50-200 lines | 300 lines |
| Asset Example | 30-100 lines | 200 lines |

## Summary

**Key principles**:
1. Start simple, add structure as needed
2. Use descriptive, consistent naming
3. Group related content together
4. Keep hierarchy shallow (< 3 levels)
5. Follow patterns from similar skills

**Quick checklist**:
- [ ] Directory structure matches skill complexity
- [ ] File names follow kebab-case convention
- [ ] SKILL.md is main entry point
- [ ] References/ contains detailed docs
- [ ] Assets/ contains templates/examples
- [ ] Structure is documented if complex
