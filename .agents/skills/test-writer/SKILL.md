---
name: test-writer
description: Write tests using glm AI assistant. Use when user asks to write tests, create test cases, or implement test coverage.
allowed-tools: Bash
model: sonnet
---

# Test Writer

This skill delegates test writing to the `glm` bash tool, which provides AI-assisted test generation.

## How It Works

When you need to write tests, delegate to glm instead of writing them manually:

```bash
glm -p "Write tests for [specific component/function/scenario]"
```

## When to Use

- User asks to write tests for new code
- User requests test coverage for existing functionality
- User mentions "test this" or "add tests"
- User asks about testing specific components

## Usage

Replace the user's testing request with a glm prompt:

```
User: "Write tests for the TradeAction entity"

Your response: Execute glm with detailed prompt
glm -p "Write comprehensive unit tests for TradeAction entity in src/shares_reporting/domain/entities.py. Include tests for initialization, validation, and business logic. Follow pytest conventions and use appropriate fixtures."
```

## Project Context

This project uses:
- **pytest** as the test framework
- **3-tier architecture**: unit, integration, e2e tests
- **Domain-driven design** with rich domain models
- Test location: `tests/unit/domain/`, `tests/unit/application/`, etc.

For detailed testing strategy, see [AGENTS.md - Testing Strategy](../../AGENTS.md#testing-strategy).
