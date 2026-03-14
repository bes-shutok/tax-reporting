# Skill Sizing Guide

Guidelines for determining optimal skill size and when to split content across multiple files.

## Size Analysis of Production Skills

Based on analysis of 50+ production skills from official Claude Code plugins:

| Size Category | Line Range | Percentage | Examples |
|---------------|------------|------------|----------|
| Small | 100-300 | 35% | temporal-python-testing (146) |
| Medium | 300-600 | 45% | api-design-principles (527) |
| Large | 600-1000+ | 20% | python-testing-patterns (907), javascript-testing-patterns (1025) |

**Key finding**: Most effective skills are in the 300-600 line range.

## Size Thresholds

### Small Skills: < 300 lines

**Characteristics**:
- Single focus
- Straightforward guidance
- No complex examples
- Minimal edge cases

**When to stay small**:
- Utility skills (formatters, linters)
- Single-purpose helpers
- Straightforward patterns
- Quick reference needed

**Example structure**:
```
my-skill/
└── SKILL.md (200-250 lines)
```

### Medium Skills: 300-600 lines

**Characteristics**:
- Multiple related patterns
- Some examples needed
- Moderate complexity
- Progressive disclosure starts

**When to grow to medium**:
- Multiple related concepts
- Need for examples (20-50 lines)
- Reference material helpful
- Domain-specific guidance

**Example structure**:
```
my-skill/
├── SKILL.md (300-400 lines)
└── references/
    └── details.md (100-200 lines)
```

### Large Skills: 600-1000+ lines

**Characteristics**:
- Comprehensive coverage
- Multiple subtopics
- Extensive examples
- Heavy progressive disclosure

**When to grow to large**:
- Framework guides
- Multiple domains covered
- Complex workflows
- Extensive reference material

**Example structure**:
```
my-skill/
├── SKILL.md (400-500 lines)
├── references/
│   ├── topic-a.md (200-300 lines)
│   ├── topic-b.md (200-300 lines)
│   └── topic-c.md (200-300 lines)
└── assets/
    ├── template.md (50-100 lines)
    └── examples.md (100-200 lines)
```

## Decision Matrix

### When to Keep in SKILL.md

Keep content in main file when:

| Content Type | Size | Keep In |
|--------------|------|---------|
| Quick start | < 50 lines | SKILL.md |
| Core principles | < 100 lines | SKILL.md |
| Common patterns | < 150 lines | SKILL.md |
| Short examples | < 30 lines each | SKILL.md |
| Overview/summary | < 50 lines | SKILL.md |

### When to Move to references/

Move content when:

| Content Type | Size | Move To |
|--------------|------|---------|
| Detailed implementation | > 100 lines | references/ |
| API documentation | > 50 lines | references/ |
| Complex examples | > 30 lines | references/ or assets/ |
| Alternative approaches | > 80 lines | references/ |
| Historical context | Any size | references/ |
| Edge case handling | > 100 lines | references/ |

### When to Move to assets/

Move content when:

| Content Type | Move To |
|--------------|---------|
| Code templates | assets/ |
| Checklists | assets/ |
| Complete examples | assets/ |
| Configuration files | assets/ |
| Scripts | assets/ or scripts/ |

## Line Count Guidelines by Section

### SKILL.md Section Targets

| Section | Target | Maximum |
|---------|--------|---------|
| Frontmatter | 5 lines | 10 lines |
| Quick Start | 30-50 lines | 75 lines |
| Core Principles | 50-100 lines | 150 lines |
| Common Patterns | 75-150 lines | 200 lines |
| Examples | 30-75 lines | 100 lines |
| Resources | 10-20 lines | 30 lines |
| **Total** | **200-400 lines** | **600 lines** |

### Reference File Targets

| File Type | Target | Maximum |
|-----------|--------|---------|
| Topic guide | 150-250 lines | 400 lines |
| Implementation | 200-300 lines | 500 lines |
| Examples collection | 100-200 lines | 300 lines |

## Content Splitting Strategies

### Strategy 1: By Topic

Split when skill covers multiple distinct topics.

**Before** (single file):
```markdown
# API Design (600 lines)

## REST APIs (200 lines)
[detailed REST guide]

## GraphQL APIs (200 lines)
[detailed GraphQL guide]

## gRPC APIs (200 lines)
[detailed gRPC guide]
```

**After** (split):
```
SKILL.md (300 lines)
├── Quick overview of all three
├── Comparison guide
└── Links to detailed references

references/
├── rest-apis.md (200 lines)
├── graphql-apis.md (200 lines)
└── grpc-apis.md (200 lines)
```

### Strategy 2: By Depth

Split by essential vs detailed content.

**Before** (single file):
```markdown
# Testing (500 lines)

## Basic Testing (50 lines)
[essentials]

## Test Structure (100 lines)
[detailed structure guide]

## Fixtures (100 lines)
[detailed fixture guide]

## Mocking (100 lines)
[detailed mocking guide]

## Parametrization (100 lines)
[detailed parametrization guide]

## Coverage (50 lines)
[coverage guide]
```

**After** (split):
```
SKILL.md (250 lines)
├── Quick start
├── Core principles
├── Basic patterns
└── Links to details

references/
├── fixtures.md (100 lines)
├── mocking.md (100 lines)
├── parametrization.md (100 lines)
└── coverage.md (50 lines)
```

### Strategy 3: By Audience

Split by novice vs advanced content.

**Before** (single file):
```markdown
# Async Python (500 lines)

## Basic Async (100 lines)
[beginner-friendly]

## Event Loops (100 lines)
[intermediate]

## Protocols (100 lines)
[advanced]

## Performance (100 lines)
[advanced]

## Debugging (100 lines)
[intermediate/advanced]
```

**After** (split):
```
SKILL.md (300 lines)
├── Getting started (beginner)
├── Common patterns (intermediate)
└── Links to advanced topics

references/
├── event-loops.md (100 lines)
├── protocols.md (100 lines)
├── performance.md (100 lines)
└── debugging.md (100 lines)
```

## Size Red Flags

### Red Flag 1: SKILL.md > 600 lines

**Problem**: Overwhelming, hard to navigate

**Solution**:
1. Identify distinct topics
2. Extract details to references/
3. Keep essentials in SKILL.md

**Target**: Reduce to 300-400 lines

### Red Flag 2: Single section > 150 lines

**Problem**: Section is too detailed

**Solution**: Extract to dedicated reference file

**Example**:
```markdown
## REST API Design (200 lines) ← Too long
[Extract to references/rest-design.md]
```

### Red Flag 3: Example > 50 lines

**Problem**: Example is too long for inline

**Solution**: Move to assets/examples.md

**Example**:
```markdown
## Example

For a complete working example, see [example.py](assets/example.py).

Basic structure:
```python
# 20-line overview
```
```

### Red Flag 4: Reference file > 400 lines

**Problem**: Reference file is too large

**Solution**: Split into multiple focused files

**Example**:
```
references/testing.md (500 lines) → Too long

Split into:
references/
├── unit-testing.md (150 lines)
├── integration-testing.md (150 lines)
├── e2e-testing.md (100 lines)
└── advanced-patterns.md (100 lines)
```

## Growth Strategy

### Start Small

**Initial release**: Single SKILL.md (200-300 lines)

**Focus**:
- Core use case
- Essential patterns
- Quick start guide

### Grow Organically

**Add content** as users request more detail

**Signs you need references/**:
- Users asking for more details
- SKILL.md growing beyond 300 lines
- Complex examples needed
- Multiple topics emerging

**Signs you need assets/**:
- Users requesting templates
- Checklists would help
- Code examples getting long

### Refactor Regularly

**Every 100 lines added**: Review structure

**Questions**:
- Can this be simplified?
- Should this move to references?
- Is this essential or nice-to-have?

**Action**: Restructure before publishing

## Size vs Discoverability

### Smaller ≠ Better

**Too small** (< 150 lines):
- May lack necessary context
- Users need to ask for clarification
- More back-and-forth

**Too large** (> 600 lines):
- Overwhelming context
- Hard to find specific info
- Slower responses

**Just right** (300-500 lines):
- Sufficient context
- Easy to navigate
- Balanced depth

### Optimal Range

**For most skills**: 300-500 lines in SKILL.md

**Breakdown**:
- 50 lines: Quick start
- 100 lines: Core principles
- 150 lines: Common patterns
- 50 lines: Examples
- 50 lines: Resources/navigation

**Total**: ~400 lines, well-structured

## Measuring Your Skill

### Count Lines

```bash
# Main skill file
wc -l .claude/skills/my-skill/SKILL.md

# All reference files
find .claude/skills/my-skill/references/ -name "*.md" -exec wc -l {} +

# Total skill size
find .claude/skills/my-skill/ -name "*.md" -exec wc -l {} + | tail -1
```

### Analyze Sections

```bash
# Count lines in each section
grep -n "^##" .claude/skills/my-skill/SKILL.md
```

### Check Reference File Sizes

```bash
# List all reference files with sizes
find .claude/skills/my-skill/references/ -name "*.md" -exec wc -l {} + | sort -n
```

## Size Optimization Tips

### Tip 1: Remove Redundancy

**Before**:
```markdown
## Principle 1
[10 lines]

## Principle 2  
[10 lines]

## Principle 3
[10 lines]

## Summary of Principles
[30 lines repeating above] ← Redundant
```

**After**:
```markdown
## Core Principles
[30 lines covering all principles]

No summary needed - principles are clear
```

### Tip 2: Use Links Instead of Repetition

**Before**:
```markdown
## REST API Design
[50 lines]

## GraphQL Design  
[50 lines]

## When to Use REST vs GraphQL
[30 lines comparing - repeats above]
```

**After**:
```markdown
## REST API Design
[30 lines overview]
See [rest.md](references/rest.md) for details

## GraphQL Design
[30 lines overview]  
See [graphql.md](references/graphql.md) for details

## Comparison
[10 lines with links to detailed guides]
```

### Tip 3: Condense Examples

**Before**:
```markdown
## Example 1: Basic Test
[50 lines]

## Example 2: Test with Fixture
[50 lines]

## Example 3: Parametrized Test
[50 lines]
```

**After**:
```markdown
## Examples

### Basic Test
[15 lines overview]

### Test with Fixture
[15 lines overview]

### Parametrized Test
[15 lines overview]

For complete working examples, see [examples.md](assets/examples.md).
```

## Real-World Size Examples

### Example 1: Grew Over Time

**Initial** (200 lines):
```
testing-patterns/
└── SKILL.md (200 lines)
```

**After feedback** (500 lines):
```
testing-patterns/
├── SKILL.md (350 lines)
└── references/
    ├── advanced.md (150 lines)
```

**Final** (900 lines):
```
testing-patterns/
├── SKILL.md (400 lines)
├── references/
│   ├── unit.md (200 lines)
│   ├── integration.md (200 lines)
│   └── advanced.md (100 lines)
└── assets/
    └── examples.md (100 lines)
```

### Example 2: Stayed Focused

**Initial** (250 lines):
```
api-versioning/
└── SKILL.md (250 lines)
```

**Final** (280 lines):
```
api-versioning/
├── SKILL.md (280 lines)
└── assets/
    └── checklist.md (30 lines)
```

**Why stayed small**: Single, focused topic

## Decision Checklist

When adding content, ask:

- [ ] Is this essential for every use?
- [ ] Will this fit in current size limits?
- [ ] Can this be condensed?
- [ ] Should this go in references/?
- [ ] Should this go in assets/?
- [ ] Is this duplicating existing content?

**If answer is "no" to first two questions**: Consider references/ or assets/.

## Summary

**Optimal sizes**:
- **Small skills**: 150-300 lines (single file)
- **Medium skills**: 300-500 lines SKILL.md + references/
- **Large skills**: 400-600 lines SKILL.md + extensive references/

**Key principles**:
1. Start small, grow organically
2. Split by topic or depth
3. Extract details to references/
4. Keep essentials in SKILL.md
5. Refactor regularly

**Goal**: Right-sized skill for optimal context usage and user experience.
