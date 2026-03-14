---
name: how-to-write-skills
description: Comprehensive guide for creating effective Codex Skills. Use when writing new skills, restructuring existing skills, or understanding skill patterns and best practices.
---

# How to Write Codex Skills

Master the art of creating effective, discoverable, and well-structured Codex Skills that enhance AI capabilities for your projects.

## Quick Start

Create your first skill in under 5 minutes:

```bash
# 1. Create skill directory
mkdir -p .Codex/skills/my-skill

# 2. Create SKILL.md with frontmatter
cat > .Codex/skills/my-skill/SKILL.md << 'EOF'
---
name: my-skill
description: What this skill does. Use when [trigger contexts like specific keywords, tasks, or scenarios].
---

# My Skill

Brief description of what this skill does.

## When to Use

- Specific scenario 1
- Specific scenario 2

## How It Works

Step-by-step explanation...

EOF
```

**With optional fields:**

```yaml
---
name: my-skill
description: Read and analyze code. Use when reviewing code quality or searching for patterns.
allowed-tools: Read, Grep, Glob  # Restrict to read-only tools
model: haiku                     # Use faster model for simple tasks
---
```

That's it! Codex will automatically discover and use your skill.

## Core Principles

### 1. Progressive Disclosure

Skills use a three-level context loading system:

**Level 1: Metadata** (always loaded)
- Frontmatter with `name` and `description`
- Determines when to trigger the skill

**Level 2: SKILL.md Body** (loaded when triggered)
- Core instructions and guidance
- Should be focused and essential

**Level 3: References** (loaded as needed)
- Detailed documentation in `references/`
- Examples, templates in `assets/`
- Loaded only when specifically referenced

### 2. Conciseness is Key

Keep SKILL.md focused:
- **Essentials only** in main file
- **Details** in references/
- **Examples** in assets/

### 3. Model-Invoked Design

Skills are automatically triggered based on:
- User request content
- Description keywords
- Context relevance

You don't invoke skills directly - the model decides when to use them.

## Skill Structure Patterns

### Simple Skill (Single File)

Everything in a single SKILL.md file - ideal for focused guidance.

```
my-skill/
└── SKILL.md
```

**Example**: Simple utilities, straightforward workflows

**Use case**: When guidance fits comfortably without overwhelming context.

### Standard Multi-File Skill (Recommended)

Flat structure with supporting files directly in skill root.

```
my-skill/
├── SKILL.md              # Required: Overview and navigation
├── REFERENCE.md          # Optional: Detailed API docs
├── EXAMPLES.md           # Optional: Usage examples
└── FORMS.md              # Optional: Form field mappings
```

**Example**: Domain-specific guidance, standard workflows

**Use case**: When you need both quick reference and detailed documentation.

**Official Note**: Codex discovers supporting files through links in SKILL.md. Files are loaded only when referenced.

### Skill with Utility Scripts

For skills that need executable scripts with zero-context execution.

```
my-skill/
├── SKILL.md              # Overview and instructions
├── REFERENCE.md          # Detailed docs
└── scripts/
    ├── helper.py         # Utility script - executed, not loaded
    └── validate.py       # Validation script
```

**Key Point**: Scripts in `scripts/` are **executed without reading** into context. Only output consumes tokens. Use for:
- Complex validation logic
- Data processing that's more reliable as tested code
- Operations requiring consistency

### Organized Skill with Subdirectories

For complex skills, use subdirectories for organization.

```
my-skill/
├── SKILL.md              # Essentials only
├── references/           # Detailed docs
│   ├── architecture.md
│   ├── implementation.md
│   └── edge-cases.md
└── scripts/              # Utility scripts
    └── helper.py
```

**Example**: Complex frameworks, comprehensive guides

**Use case**: When covering extensive topics with many reference files.

## When to Use Reference Files

Move content to `references/` when:

- **Detailed API documentation** (> 50 lines of API specs)
- **Complex examples** (> 100 lines of code)
- **Alternative approaches** (multiple valid solutions)
- **Historical context** (background information)
- **Database schemas** (large data models)
- **Edge case handling** (extensive error scenarios)

Keep in SKILL.md:

- Quick start guide
- Core principles
- Common usage patterns
- Navigation to references

## Frontmatter Requirements

### Required Fields

```yaml
---
name: skill-name              # Required: lowercase-with-hyphens, max 64 chars
description: What + When      # Required: max 1024 chars
---
```

**Validation Rules:**
- `name` must use lowercase letters, numbers, and hyphens only (max 64 chars)
- `name` should match the directory name
- `description` must answer two questions: (1) What does it do? (2) When should Codex use it?
- Frontmatter must start with `---` on line 1 (no blank lines before)
- Frontmatter must end with `---` before the Markdown content
- Use spaces for indentation, not tabs
- File must be named `SKILL.md` (case-sensitive)

### Description Best Practices

**Pattern**: [WHAT it does] + [WHEN to use it]

**Bad Examples:**
- "Helps with testing" ❌ (too vague, no triggers)
- "API design guide" ❌ (missing when to use)
- "Code formatter" ❌ (no context)

**Good Examples:**
- "Run pytest tests after code changes. Use when modifying source code, before committing, or when user mentions running tests." ✅
- "Design REST and GraphQL APIs. Use when creating new APIs, reviewing API specifications, or establishing API design standards." ✅
- "Format Python code with Ruff. Use when user mentions formatting, linting, or code style." ✅

### Optional Fields

```yaml
---
name: skill-name
description: What + When
allowed-tools: Read, Grep, Glob  # Optional: Restrict tool access
model: haiku                     # Optional: Use specific model (haiku, opus, sonnet)
---
```

**Optional Fields Explained:**

- **`allowed-tools`**: Restricts which tools the skill can access. Useful for:
  - Security: Limit skills that only need to read files
  - Performance: Prevent unnecessary tool loading
  - Focus: Ensure skills stay in their lane
  - Common values: `Read`, `Grep`, `Glob`, `Edit`, `Write`, `Bash`
  - **Tool-specific syntax**: `Bash(python:*)` allows only Python commands via Bash

- **`model`**: Specifies which model to use for the skill. Useful for:
  - Cost optimization: Use `haiku` for simple, deterministic tasks
  - Quality: Use `opus` for complex reasoning
  - Speed: Use `haiku` for quick reference lookups
  - Default: Inherits from parent session if not specified

## Common Mistakes to Avoid

### 1. Vague Descriptions

**Problem**: Skill never triggers because description lacks keywords.

**Solution**: Include specific trigger contexts:
```yaml
# ❌ Bad
description: Helps with documentation

# ✅ Good
description: Generate technical documentation from code. Use when user mentions docs, API reference, or documentation generation.
```

### 2. Excessive Length

**Problem**: SKILL.md is 1000+ lines, overwhelming context.

**Solution**: Use progressive disclosure:
- Keep main file under 400 lines
- Move details to `references/`
- Use examples in `assets/`

### 3. Missing Navigation

**Problem**: Users can't find related information.

**Solution**: Always include resource links:
```markdown
## Additional Resources

- **Detailed Guide**: See [detailed-topic.md](references/detailed-topic.md)
- **Quick Reference**: See [quick-ref.md](references/quick-ref.md)
```

### 4. Wrong Location

**Problem**: Skill not discovered because it's in the wrong directory.

**Solution**:
- **Project skills**: `.Codex/skills/` (in project root)
  - Use for project-specific skills
  - Takes precedence over global skills when names conflict
- **Global skills**: `~/.Codex/skills/` (fully supported in 2025)
  - Use for skills you want available across all projects
  - Great for personal workflows and common patterns

### 5. Duplicate Content

**Problem**: Same information in SKILL.md and references.

**Solution**: 
- SKILL.md: Essentials and summaries
- References: Deep dives and details
- Never copy-paste content between files

## Skill Size Guidelines

Based on analysis of 50+ production skills:

| Size Range | Line Count | Recommendation |
|------------|------------|----------------|
| Small | < 300 | Single SKILL.md |
| Medium | 300-600 | SKILL.md + references/ |
| Large | > 600 | Heavy progressive disclosure |

**Real-world examples**:
- `temporal-python-testing`: 146 lines (small, focused)
- `api-design-principles`: 527 lines (medium, uses references/)
- `python-testing-patterns`: 907 lines (large, comprehensive)
- `javascript-testing-patterns`: 1025 lines (large, extensive)

## Testing Your Skills

### 1. Test Discovery
```
Ask: "What skills are available?"
Expected: Your skill appears in the list
```

### 2. Test Triggering
```
Ask: [Task matching your description]
Expected: Skill is automatically invoked
```

### 3. Test Execution
```
Ask: [Specific question the skill should answer]
Expected: Accurate, helpful response
```

### 4. Test Navigation
```
Ask: "Tell me more about [topic in references]"
Expected: Reference files are loaded and used
```

## Directory Organization

### Standard Structure

```
skill-name/
├── SKILL.md              # Required: Main skill file
├── references/           # Optional: Detailed docs
│   ├── topic1.md
│   └── topic2.md
└── assets/              # Optional: Templates, examples
    ├── template.md
    └── checklist.md
```

### File Naming

- **Main file**: Always `SKILL.md` (uppercase)
- **References**: `kebab-case.md` (lowercase with hyphens)
- **Assets**: `kebab-case.md`

### When to Add Subdirectories

**scripts/**: When skill needs executable scripts
```
skill-name/
└── scripts/
    └── generate-docs.py
```

**templates/**: When skill has many code templates
```
skill-name/
└── templates/
    ├── python-template.py
    └── javascript-template.js
```

## Real Examples from Production Skills

### Example 1: Simple Skill (Official Pattern)

**generating-commit-messages** (from official docs)
- Single SKILL.md file
- Clear trigger: "writing commit messages or reviewing staged changes"
- Step-by-step instructions with best practices

**Structure:**
```
commit-helper/
└── SKILL.md
```

### Example 2: Standard Multi-File Skill (Official Pattern)

**pdf-processing** (from official docs)
- SKILL.md with quick start
- FORMS.md for form field mappings
- REFERENCE.md for detailed API docs
- scripts/ for utility scripts (fill_form.py, validate.py)

**Structure:**
```
pdf-processing/
├── SKILL.md              # Overview and quick start
├── FORMS.md              # Form field mappings and filling instructions
├── REFERENCE.md          # API details for pypdf and pdfplumber
└── scripts/
    ├── fill_form.py      # Utility to populate form fields
    └── validate.py       # Checks PDFs for required fields
```

**Frontmatter:**
```yaml
---
name: pdf-processing
description: Extract text, fill forms, merge PDFs. Use when working with PDF files, forms, or document extraction. Requires pypdf and pdfplumber packages.
allowed-tools: Read, Bash(python:*)
---
```

**Note**: `Bash(python:*)` restricts Bash to only run Python commands.

### Example 3: Organized Skill with Subdirectories

**api-design-principles**
- Main SKILL.md with core patterns
- references/ for detailed guides:
  - `rest-best-practices.md`
  - `graphql-schema-design.md`

**Structure:**
```
api-design-principles/
├── SKILL.md              # Core instructions (~527 lines)
└── references/
    ├── rest-best-practices.md
    └── graphql-schema-design.md
```

### Example 4: Project-Specific Skill

**run-project-tests** (this project)
- Single SKILL.md
- Project-specific testing guidance
- UV and pytest commands
- No references needed

## Best Practices Summary

### DO:
- ✅ Include WHAT + WHEN in description
- ✅ Keep SKILL.md under 400 lines when possible
- ✅ Use progressive disclosure for complex topics
- ✅ Link to references and assets
- ✅ Test skill discovery and triggering
- ✅ Use lowercase-with-hyphens for names
- ✅ Place skills in `.Codex/skills/`

### DON'T:
- ❌ Write vague descriptions without triggers
- ❌ Create 1000+ line SKILL.md files
- ❌ Duplicate content between files
- ❌ Put skills in wrong locations
- ❌ Forget to test the skill
- ❌ Use camelCase or spaces in names
- ❌ Mix details with essentials

## Security Considerations

### Using `allowed-tools` for Security

The `allowed-tools` field is an important security feature that helps:

**1. Principle of Least Privilege**
- Only grant tools that are absolutely necessary
- Read-only skills should use `allowed-tools: Read, Grep, Glob`
- Prevents accidental modifications

**2. Skill Isolation**
- Skills that analyze code shouldn't write files
- Documentation skills shouldn't execute bash commands
- Keeps skills focused and safe

**3. Common Patterns**

```yaml
# Documentation skill (read-only)
---
name: api-docs
description: Generate API documentation. Use when user asks for docs.
allowed-tools: Read, Grep, Glob
---

# Code review skill (read-only)
---
name: code-reviewer
description: Review code for quality and security. Use when user mentions review.
allowed-tools: Read, Grep, Glob
---

# Python processing skill (Bash restricted to Python only)
---
name: pdf-processing
description: Extract text, fill forms, merge PDFs. Use when working with PDF files.
allowed-tools: Read, Bash(python:*)
---

# Testing skill (needs execution)
---
name: test-runner
description: Run tests and report results. Use when user mentions testing.
allowed-tools: Bash, Read, Grep
---

# Full development skill (all tools)
---
name: developer
description: Complete development workflow. Use for feature implementation.
# No allowed-tools restriction = all tools available
---
```

**4. Tool-Specific Syntax**

You can restrict tools to specific operations:
- `Bash(python:*)` - Only allow Python commands via Bash
- `Bash(node:*)` - Only allow Node.js commands via Bash
- `Read, Grep, Glob` - Multiple tools (comma-separated)

**5. When to Restrict Tools**

Restrict tools when:
- Skill is for analysis/review only
- Skill should never modify files
- Skill provides reference information
- Skill is used in sensitive contexts

Don't restrict when:
- Skill's primary purpose is file modification
- Skill needs full development capabilities
- User expects complete functionality


## Troubleshooting

### Skill Not Discovered

**Symptoms**: Skill doesn't appear in available skills list

**Solutions**:
1. Check file location: `.Codex/skills/skill-name/SKILL.md`
2. Verify frontmatter syntax (valid YAML)
3. Check file name is `SKILL.md` (uppercase)
4. Restart Codex session

### Skill Not Triggering

**Symptoms**: Skill exists but doesn't invoke automatically

**Solutions**:
1. Improve description with trigger keywords
2. Check if keywords match user requests
3. Test with explicit trigger phrases
4. Review similar skills' descriptions

### Context Overflow

**Symptoms**: Skill response is cut off or incomplete

**Solutions**:
1. Move details to `references/`
2. Reduce SKILL.md line count
3. Use more concise language
4. Split into multiple focused skills

## Additional Resources

### Detailed Guides
- **Skill Structure**: See [skill-structure.md](references/skill-structure.md)
- **Frontmatter Guide**: See [frontmatter-guide.md](references/frontmatter-guide.md)
- **Progressive Disclosure**: See [progressive-disclosure.md](references/progressive-disclosure.md)
- **Size Guidelines**: See [skill-sizes.md](references/skill-sizes.md)

## Quick Reference

| Task | Command/Action |
|------|----------------|
| Create skill | `mkdir -p .Codex/skills/my-skill` |
| Test discovery | Ask "What skills are available?" |
| Test triggering | Ask task matching description |
| Check size | `wc -l .Codex/skills/my-skill/SKILL.md` |
| Add references | Create `references/` directory |
| Add assets | Create `assets/` directory |

## Key Takeaways

1. **Description matters**: Include WHAT + WHEN with trigger keywords
2. **Size matters**: Keep SKILL.md focused, use references for details
3. **Location matters**: Use `.Codex/skills/` for project skills
4. **Structure matters**: Follow progressive disclosure pattern
5. **Testing matters**: Verify discovery, triggering, and execution

Write skills that enhance AI capabilities without overwhelming context. The best skills are concise, well-structured, and automatically discoverable.
