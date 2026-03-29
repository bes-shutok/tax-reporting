# Frontmatter Guide

Complete guide to YAML frontmatter for Claude Code Skills.

## Required Fields

### name

**Format**: `name: skill-name`

**Rules**:
- Required: Yes
- Max length: 64 characters
- Format: lowercase with hyphens
- Pattern: `^[a-z][a-z0-9-]*[a-z0-9]$`

**Examples**:
```yaml
# ✅ Good
name: test-runner
name: api-designer
name: code-formatter
name: pdf-extractor

# ❌ Bad
name: TestRunner          # no caps
name: test_runner         # no underscores
name: test                # too short, unclear
name: this-is-a-very-long-skill-name-that-exceeds-recommended-length  # too long
```

### description

**Format**: `description: What it does + When to use it`

**Rules**:
- Required: Yes
- Max length: 1024 characters
- Must include: WHAT + WHEN
- Should include: Trigger keywords

**Pattern**:
```
[Verb] [what the skill does]. Use when [trigger contexts].
```

**Examples**:
```yaml
# ✅ Good - Clear WHAT + WHEN with triggers
description: Run pytest tests after code changes. Use when modifying source code, before committing, or when user mentions running tests.
description: Design REST and GraphQL APIs. Use when creating new APIs, reviewing specifications, or establishing design standards.
description: Format Python code with Ruff. Use when user mentions formatting, linting, or code style improvements.
description: Extract text and tables from PDF files. Use when working with PDFs or when user mentions PDF extraction.

# ❌ Bad - Missing WHEN, no triggers
description: Helps with testing
description: API design guide
description: Code formatter
description: PDF tool
```

## Optional Fields

### allowed-tools

**Format**: `allowed-tools: Tool1, Tool2, Tool3`

**Purpose**: Restrict which tools the skill can access

**Rules**:
- Required: No
- Default: All tools available
- Format: Comma-separated list
- Tools: Read, Write, Edit, Bash, Grep, Glob, etc.

**Examples**:
```yaml
# Read-only analysis skill
allowed-tools: Read, Grep, Glob

# File modification skill
allowed-tools: Read, Write, Edit

# Full development skill
allowed-tools: Read, Write, Edit, Bash, Grep, Glob
```

**When to use**:
- Skill should only read files (code review, analysis)
- Security considerations (limit write access)
- Performance (reduce tool overhead)

**When NOT to use**:
- Most skills (let skill use whatever tools needed)
- Learning/exploration (full tool access)

### model

**Format**: `model: model-name`

**Purpose**: Specify which AI model to use

**Rules**:
- Required: No
- Default: System default
- Options: sonnet, opus, haiku

**Examples**:
```yaml
# Fast operations
model: haiku

# Balanced performance
model: sonnet

# Complex reasoning
model: opus
```

**When to use**:
- Skill needs fast responses (haiku)
- Skill needs deep reasoning (opus)
- Skill has specific model requirements

**When NOT to use**:
- Most skills (let system choose)
- Unclear about model needs

## Complete Frontmatter Examples

### Minimal Frontmatter (Small Skills)

```yaml
---
name: code-formatter
description: Format code using project linters. Use when user mentions formatting, linting, or code style.
---
```

### Standard Frontmatter (Medium Skills)

```yaml
---
name: api-designer
description: Design REST and GraphQL APIs. Use when creating new APIs, reviewing specifications, or establishing design standards.
allowed-tools: Read, Write, Edit
---
```

### Complete Frontmatter (Large Skills)

```yaml
---
name: framework-guide
description: Comprehensive framework development guide. Use when building new features, refactoring components, or establishing architecture patterns.
allowed-tools: Read, Write, Edit, Bash, Grep, Glob
model: sonnet
---
```

## Description Writing Guide

### The WHAT + WHEN Pattern

**WHAT**: What the skill does (action + object)

**WHEN**: When to use it (trigger contexts)

### Template Patterns

**Pattern 1: Action-Based**
```
[Verb] [object] [context]. Use when [trigger 1], [trigger 2], or [trigger 3].
```

Example:
```yaml
description: Run pytest tests after code changes. Use when modifying source code, before committing, or when user mentions running tests.
```

**Pattern 2: Domain-Based**
```
[Domain] [action] [context]. Use when [scenario 1], [scenario 2], or [scenario 3].
```

Example:
```yaml
description: REST and GraphQL API design principles. Use when designing new APIs, reviewing API specifications, or establishing API design standards.
```

**Pattern 3: Tool-Based**
```
[Tool] [action] [context]. Use when user mentions [trigger 1], [trigger 2], or [trigger 3].
```

Example:
```yaml
description: Format Python code with Ruff. Use when user mentions formatting, linting, or code style improvements.
```

### Trigger Keywords

Include keywords that users commonly use:

| Domain | Trigger Keywords |
|--------|-----------------|
| Testing | test, pytest, testing, unit test, coverage |
| API | API, endpoint, route, REST, GraphQL, schema |
| Database | database, query, SQL, migration, schema |
| Frontend | component, UI, frontend, React, Vue |
| Backend | backend, service, API, server |
| DevOps | deploy, CI/CD, pipeline, docker |
| Documentation | docs, documentation, README, API doc |

### Description Anti-Patterns

**Too Vague**:
```yaml
# ❌ Bad
description: Helps with code
description: API tool
description: Testing helper
```

**Too Long**:
```yaml
# ❌ Bad (exceeds recommended focus)
description: This skill provides comprehensive guidance on writing effective tests for Python applications using the pytest framework, including unit tests, integration tests, end-to-end tests, and also covers test fixtures, mocking, parametrization, coverage reporting, and continuous integration setup.
```

**Too Technical**:
```yaml
# ❌ Bad (assumes too much knowledge)
description: Implements TDD with pytest fixtures, monkeypatch, and parametrized tests using conftest.py patterns.
```

**Just Right**:
```yaml
# ✅ Good
description: Write pytest tests for Python applications. Use when creating tests, adding test coverage, or implementing TDD workflows.
```

## YAML Syntax Rules

### Basic Syntax

```yaml
---
name: skill-name
description: Skill description here
---
```

**Key Points**:
- Start with `---` (three hyphens)
- End with `---` (three hyphens)
- Use `key: value` format
- Space after colon
- No quotes required (unless special characters)

### Quoting Values

**When to quote**:
- Values with colons: `description: "Time: 5 minutes"`
- Values with special chars: `name: "special-skill-name"`
- Values starting with numbers: `description: "1st step guide"`

**Examples**:
```yaml
# No quotes needed
name: simple-skill
description: Simple description

# Quotes needed
description: "Format: JSON, YAML, XML"
name: "123-step-guide"
```

### Multi-line Descriptions

If description is very long (approaching 1024 chars), you can use YAML multi-line syntax:

```yaml
description: >
  Comprehensive guide for creating effective Claude Code Skills.
  Use when writing new skills, restructuring existing skills, or
  understanding skill patterns and best practices.
```

**Note**: The `>` fold style treats newlines as spaces.

### Comments

```yaml
---
# This is a comment
name: my-skill
description: My skill description  # Inline comment
---
```

## Common Frontmatter Errors

### Error 1: Missing Hyphens

```yaml
# ❌ Bad
name: my-skill
description: My description

# ✅ Good
---
name: my-skill
description: My description
---
```

### Error 2: No Space After Colon

```yaml
# ❌ Bad
name:my-skill
description:My description

# ✅ Good
name: my-skill
description: My description
```

### Error 3: Invalid Characters in Name

```yaml
# ❌ Bad
name: My_Skill
name: MySkill
name: my skill

# ✅ Good
name: my-skill
name: my-skill-v2
```

### Error 4: Description Too Vague

```yaml
# ❌ Bad
description: Helps with code

# ✅ Good
description: Refactor Python code for better maintainability. Use when improving code structure, reducing complexity, or applying design patterns.
```

## Validation Checklist

Before publishing your skill, verify:

- [ ] Frontmatter starts and ends with `---`
- [ ] `name` field present and follows kebab-case
- [ ] `description` field present with WHAT + WHEN
- [ ] `description` includes trigger keywords
- [ ] Description length < 1024 characters
- [ ] Name length < 64 characters
- [ ] YAML syntax is valid (no syntax errors)
- [ ] Optional fields used appropriately

## Testing Frontmatter

### Test 1: YAML Validation

```bash
# Use Python to validate YAML
python3 -c "import yaml; yaml.safe_load(open('.claude/skills/my-skill/SKILL.md'))"
```

Should return no errors.

### Test 2: Length Check

```bash
# Check description length
grep '^description:' .claude/skills/my-skill/SKILL.md | cut -c14- | wc -c
```

Should be < 1024.

### Test 3: Name Format

```bash
# Check name is kebab-case
grep '^name:' .claude/skills/my-skill/SKILL.md | grep -E 'name: [a-z][a-z0-9-]*[a-z0-9]'
```

Should match.

## Quick Reference

| Field | Required? | Format | Max Length |
|-------|-----------|--------|------------|
| name | Yes | kebab-case | 64 chars |
| description | Yes | WHAT + WHEN | 1024 chars |
| allowed-tools | No | Tool1, Tool2 | N/A |
| model | No | Model name | N/A |

## Best Practices Summary

1. **Always include WHAT + WHEN** in description
2. **Use lowercase with hyphens** for names
3. **Include trigger keywords** in description
4. **Keep descriptions focused** and concise
5. **Quote values with special characters**
6. **Validate YAML syntax** before publishing
7. **Test skill discovery** after creating
8. **Use optional fields sparingly** (only when needed)
