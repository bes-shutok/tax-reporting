# Progressive Disclosure Guide

Understanding and implementing progressive disclosure in Claude Code Skills for optimal context management and user experience.

## What is Progressive Disclosure?

Progressive disclosure is a design pattern that reveals information gradually, showing only what's necessary at each level and providing more details on demand.

In Claude Code Skills, this means:
- **Level 1**: Metadata (name, description) - always visible
- **Level 2**: SKILL.md body - loaded when skill triggers
- **Level 3**: References and assets - loaded when explicitly needed

## The Three Levels

### Level 1: Metadata (Always Loaded)

**Location**: Frontmatter in SKILL.md

**Content**:
```yaml
---
name: skill-name
description: What it does + When to use it
---
```

**Purpose**: 
- Skill discovery
- Trigger matching
- Quick identification

**Size**: ~100-200 bytes

**When it's loaded**: Every session, for all skills

### Level 2: SKILL.md Body (Triggered)

**Location**: Main content in SKILL.md

**Content**:
- Quick start guide
- Core principles
- Common patterns
- Navigation to references

**Purpose**:
- Immediate guidance
- Essential information
- Overview and context

**Size**: 200-500 lines ideal

**When it's loaded**: When skill is triggered by user request

### Level 3: References and Assets (On-Demand)

**Location**: `references/` and `assets/` directories

**Content**:
- Detailed documentation
- Code examples
- Templates
- Checklists

**Purpose**:
- Deep dives
- Specific implementations
- Reference material

**Size**: Individual files 50-300 lines

**When it's loaded**: When explicitly referenced from SKILL.md

## Why Progressive Disclosure Matters

### Benefit 1: Context Efficiency

Claude has limited context window. Progressive disclosure ensures:
- Only relevant information is loaded
- Context isn't overwhelmed with unused details
- Response quality remains high

**Example**:
```
Bad: Single 1000-line file always loaded
Good: 300-line SKILL.md + references loaded on demand
```

### Benefit 2: Faster Discovery

Users can quickly understand:
- What skills are available (Level 1)
- What each skill does (Level 1 description)
- How to get started (Level 2 quick start)

**Without loading**: All implementation details, examples, edge cases

### Benefit 3: Better Maintainability

Separating content by level:
- Makes updates easier
- Reduces duplication
- Improves organization

## Implementing Progressive Disclosure

### Step 1: Design Level 1 (Metadata)

**Goal**: Make skill discoverable and triggerable

**Questions**:
1. What should this skill be called?
2. What does it do?
3. When should it trigger?

**Example**:
```yaml
---
name: api-designer
description: Design REST and GraphQL APIs. Use when creating new APIs, reviewing specifications, or establishing design standards.
---
```

**Key points**:
- Name is descriptive and short
- Description includes WHAT + WHEN
- Trigger keywords are present

### Step 2: Design Level 2 (SKILL.md)

**Goal**: Provide essential guidance

**Structure**:
```markdown
# Skill Name

One-paragraph overview...

## Quick Start
[Immediate value - how to use in 5 minutes]

## Core Principles
[Essential concepts - 3-5 key points]

## Common Patterns
[Frequently used approaches]

## When to Use
[Specific scenarios - when to invoke this skill]

## Additional Resources
- **Deep Dive**: See [topic.md](references/topic.md)
- **Examples**: See [examples.md](assets/examples.md)
```

**What to include**:
- Quick start (immediate value)
- Core principles (essential concepts)
- Common patterns (frequently used)
- Navigation (links to details)

**What to exclude**:
- Extensive examples (> 20 lines)
- Implementation details
- Edge cases
- Historical context

### Step 3: Design Level 3 (References/Assets)

**Goal**: Provide detailed information on demand

**references/** structure:
```markdown
# [Topic Name]

## Background
[Context and history]

## Detailed Implementation
[Step-by-step guide]

## Examples
[Real-world usage]

## Edge Cases
[Unusual scenarios]

## See Also
[Related references]
```

**assets/** structure:
```markdown
# Template: [Name]

[Copy-paste template]

## Usage
[How to use this template]

## Customization
[How to adapt for your needs]
```

## Content Segmentation Examples

### Example 1: API Design Skill

**Level 1: Metadata**
```yaml
---
name: api-designer
description: Design REST and GraphQL APIs. Use when creating new APIs, reviewing specifications, or establishing design standards.
---
```

**Level 2: SKILL.md (400 lines)**
- Quick start: Basic endpoint design
- Core principles: REST vs GraphQL
- Common patterns: CRUD, pagination
- Resources: Links to detailed guides

**Level 3: References/** (3 files, 800 lines total)
- `rest-best-practices.md` (300 lines)
- `graphql-schema-design.md` (300 lines)
- `api-versioning.md` (200 lines)

**Result**: User gets essentials immediately, details on demand.

### Example 2: Testing Skill

**Level 1: Metadata**
```yaml
---
name: test-writer
description: Write pytest tests for Python applications. Use when creating tests, adding coverage, or implementing TDD workflows.
---
```

**Level 2: SKILL.md (350 lines)**
- Quick start: Basic test structure
- Core principles: Arrange-Act-Assert, fixtures
- Common patterns: Parametrization, mocking
- Resources: Links to advanced topics

**Level 3: References/** (4 files, 1000 lines total)
- `unit-testing.md` (250 lines)
- `integration-testing.md` (250 lines)
- `async-testing.md` (250 lines)
- `test-doubles.md` (250 lines)

**Result**: Quick reference for common cases, deep dives for specifics.

## Navigation Patterns

### Pattern 1: Resource Section

Include at end of SKILL.md:

```markdown
## Additional Resources

### Detailed Guides
- **REST API Design**: See [rest-best-practices.md](references/rest-best-practices.md)
- **GraphQL Schema**: See [graphql-schema-design.md](references/graphql-schema-design.md)

### Templates
- **API Template**: See [rest-api-template.py](assets/rest-api-template.py)
- **Checklist**: See [api-review.md](assets/api-review.md)
```

### Pattern 2: Inline References

Link from specific sections:

```markdown
## Error Handling

For comprehensive error handling patterns, see [error-handling.md](references/error-handling.md).

Common errors:
- 400 Bad Request
- 401 Unauthorized
- [See full list in references](references/status-codes.md#error-codes)
```

### Pattern 3: Decision Trees

Guide users to appropriate resources:

```markdown
## Choosing an Approach

**Need simple CRUD?**
→ See [basic-patterns.md](references/basic-patterns.md)

**Need complex workflows?**
→ See [advanced-patterns.md](references/advanced-patterns.md)

**Need real-time updates?**
→ See [websocket-patterns.md](references/websocket-patterns.md)
```

## Sizing Guidelines

### Level 2 (SKILL.md) Targets

| Skill Type | Target Lines | Maximum |
|------------|--------------|---------|
| Utility | 150-250 | 300 |
| Pattern | 250-400 | 500 |
| Framework | 350-500 | 600 |

**If exceeding maximum**: Move content to Level 3.

### Level 3 (References) Targets

| File Type | Target Lines | Maximum |
|-----------|--------------|---------|
| Topic guide | 150-250 | 400 |
| Implementation | 200-300 | 500 |
| Examples | 100-200 | 300 |

**If exceeding maximum**: Split into multiple files.

## When to Use Each Level

### Use Level 1 Only
- Very simple utilities
- One-line helpers
- Configuration presets

**Example**:
```yaml
---
name: python-version
description: Set Python version to 3.13. Use when initializing new Python projects.
---
```

### Use Level 1 + 2 (Most Common)
- Most skills fall here
- Quick reference needed
- Moderate complexity

**Example**: Testing skill, API design skill

### Use Level 1 + 2 + 3
- Complex frameworks
- Multiple related topics
- Extensive examples needed

**Example**: Full-stack framework guide, DevOps automation

## Common Mistakes

### Mistake 1: Everything in SKILL.md

**Problem**: 1000+ line SKILL.md overwhelms context

**Solution**: Extract details to references/

```markdown
# Before (SKILL.md - 1000 lines)
## API Design
[50 lines of REST basics]
[100 lines of GraphQL]
[50 lines of versioning]
[...]

# After (SKILL.md - 350 lines)
## API Design
Quick overview of REST and GraphQL...

For detailed patterns:
- **REST**: See [rest.md](references/rest.md)
- **GraphQL**: See [graphql.md](references/graphql.md)
- **Versioning**: See [versioning.md](references/versioning.md)
```

### Mistake 2: No Navigation

**Problem**: Users can't find related information

**Solution**: Always include resource links

```markdown
# Bad (no links)
## Testing
[Basic info]

# Good (with navigation)
## Testing
[Basic info]

**Learn More**:
- [Advanced Testing](references/advanced.md)
- [Test Doubles](references/mocking.md)
- [Coverage](references/coverage.md)
```

### Mistake 3: Duplication

**Problem**: Same content in SKILL.md and references

**Solution**: 
- SKILL.md: Summaries and overviews
- References: Details and implementations

```markdown
# Bad (duplicated)
## SKILL.md
## REST Principles
1. Resources are nouns
2. Use HTTP methods
[full explanation]

## references/rest.md
## REST Principles
1. Resources are nouns
2. Use HTTP methods
[same explanation]

# Good (layered)
## SKILL.md
## REST Principles
Quick overview of REST design patterns...
See [rest.md](references/rest.md) for detailed guide.

## references/rest.md
## REST Principles
Comprehensive guide to REST API design...
[full details]
```

## Testing Progressive Disclosure

### Test 1: Discovery
```
Ask: "What skills are available?"
Verify: All skills listed with names and descriptions
```

### Test 2: Quick Access
```
Ask: "How do I [task]?"
Verify: SKILL.md loaded with quick start
Verify: References NOT loaded yet
```

### Test 3: Deep Dive
```
Ask: "Tell me more about [specific topic]"
Verify: Appropriate reference file loaded
Verify: Content is detailed and comprehensive
```

### Test 4: Navigation
```
Ask: "What resources are available?"
Verify: Resource links visible and working
```

## Best Practices Summary

### DO:
- ✅ Keep SKILL.md focused on essentials
- ✅ Extract details to references/
- ✅ Provide clear navigation
- ✅ Use descriptive link text
- ✅ Organize references by topic
- ✅ Test each level independently

### DON'T:
- ❌ Put everything in SKILL.md
- ❌ Duplicate content across levels
- ❌ Hide important information in references
- ❌ Use generic link text ("click here")
- ❌ Create deep reference hierarchies
- ❌ Forget to test navigation

## Quick Decision Tree

```
Need to add content to skill?
│
├─ Is it essential for every use?
│  └─ YES → Put in SKILL.md
│
├─ Is it detailed implementation?
│  └─ YES → Put in references/
│
├─ Is it a template or example?
│  └─ YES → Put in assets/
│
└─ Is it nice-to-have?
   └─ YES → Consider omitting or putting in references/
```

## Summary

**Progressive disclosure ensures**:
1. Fast skill discovery (Level 1 metadata)
2. Immediate value (Level 2 essentials)
3. Deep details available (Level 3 references)

**Key principles**:
- Essentials in SKILL.md
- Details in references/
- Clear navigation between levels
- No duplication across levels
- Test each level independently

**Result**: Optimal context usage and user experience.
