# Skill Authoring Guide

A `SKILL.md` should be a small, reusable task playbook for an agent. Skills are meant for repeatable workflows that benefit from richer instructions, references, or scripts without bloating always-on context, while `AGENTS.md` is for durable project guidance that should apply before work starts. ([Claude][2])

## What goes where

- `AGENTS.md` lives at repo level and contains repo-wide defaults, conventions, and guardrails.
- Each skill lives in its own directory.
- `SKILL.md` is the entry point for that skill.
- `scripts/` contains deterministic helpers used by that skill.
- `reference.md`, `examples.md`, and `templates/` contain supporting material for that skill.

That split is a synthesis, but it follows the way OpenAI documents `AGENTS.md` as layered project instruction and both vendors document skills as reusable instruction bundles with optional scripts/resources. ([Claude][2])

## 8 core rules

### 1. One skill, one job

Keep each skill narrowly scoped. OpenAI explicitly recommends keeping each skill scoped to one job, starting from a few concrete use cases, defining clear inputs and outputs, and only adding scripts/assets when they improve reliability. ([OpenAI Developers][3])

Good:


* debugging-flaky-pytest
* generating-release-notes-from-prs

Bad:

* testing helper
* backend workflow

If the name sounds vague, the scope is probably too broad.

### 2. The description is the router

The description is the most important line in the skill. Anthropic says the description should include both what the skill does and when to use it, and that it is critical for skill selection; OpenAI says much the same. ([Claude][1])

It should say:

* what the skill does
* when to use it
* enough trigger wording that the agent can pick it reliably

Bad:

```md
description: Generate release notes
```

Better:

```md
description: Generate a markdown changelog from merged PRs since the last tag, grouped by conventional-commit type. Use when asked for release notes, a changelog, or "what changed since X".
```

For simple skills, the description is enough. Only add separate “use this skill when” / “do not use this skill when” sections when the boundary is easy to get wrong. 

### 3. Keep `SKILL.md` small

Anthropic explicitly recommends keeping the main `SKILL.md` body under 500 lines and moving bulk into separate files using progressive disclosure. ([Claude][1])

Put bulk into:

* `reference.md`
* `examples.md`
* `templates/`
* `scripts/`

A good `SKILL.md` is usually a dispatcher plus workflow.

### 4. Write procedures, not essays

Anthropic recommends explicit workflows and feedback loops for complex tasks, and OpenAI recommends concrete inputs, outputs, and representative use cases rather than generalities. ([Claude][1])

A skill should mostly say:

* inspect these files
* run this command
* if this case happens, follow this branch
* validate
* fix and rerun if needed

Prefer explicit steps over explanation.

### 5. Script deterministic work

Anthropic explicitly recommends utility scripts because they are more reliable than regenerated code, save tokens, and improve consistency. ([Claude][2])

Use scripts for things the model should not keep reinventing:

* parsing logs
* extracting structured fields
* normalizing data
* generating reports
* validating output
* running fixed command sequences
* if applicable, summarize file changes / additions

Keep scripts runnable outside any specific agent runtime. 

### 6. Make scripts tiny CLIs

OpenAI recommends designing skill scripts like small command-line tools, and Anthropic says scripts should have clear documentation and explicit error handling. ([Claude][1])

A helper script should usually document just:

* purpose
* usage
* exit behavior
* requirements (e.g. access tokens, libraries)

Example:

```py
#!/usr/bin/env python3
"""
Purpose: Extract failing tests from CI logs.

Usage:
    python3 scripts/extract_failures.py <log_dir>
"""
```

If the script writes a file, note the output path too.

### 7. Include execution-time validation

Every nontrivial skill should include an explicit validation step that runs while the skill is being executed. Anthropic’s best-practices doc gives this exact pattern: validate immediately, inspect the error, fix, rerun, and only proceed once validation passes. In order to prevent thrashing, set a limit on the number of reruns, e.g. 2-3 times. ([Claude][1])

Include:

* a concrete validator, test, or linter command
* a fix-and-rerun loop
* clear stop conditions when the agent should report instead of thrashing

Default loop:

1. do the work
2. run validator/test/linter
3. inspect failure
4. repair
5. rerun

Example validators:

* `pytest tests/integration/test_auth.py -q`
* `go test ./cmd/foo/...`
* `python scripts/validate_manifest.py out/manifest.json`

Treat this as part of the skill’s runtime workflow.

### 8. Evaluate the skill with test prompts

Separately from runtime validation, each skill should have a small set of author-side evaluation prompts to check whether the agent triggers the skill when it should, and avoids triggering it when it should not. Anthropic recommends testing skills with real usage and creating evaluations, while OpenAI’s eval guidance explicitly calls out trigger behavior, process-following, style, and efficiency as things to measure. ([Claude][1])

Keep 2–4 prompts:

* one clear positive trigger
* one near-miss / out-of-scope case
* optionally one edge case

Example for a release-notes skill:

```md
Example test prompts:

Positive:
- "Please prepare release notes from the PRs merged since v1.4.0."
- "What changed since the last tag? Write a changelog in markdown."

Near-miss / should not trigger:
- "Summarize the architecture of the release pipeline."

Edge case:
- "Generate release notes since commit abc123, but exclude docs-only changes."
```

Put prompts in a separate file, e.g. `examples.md`


## Supporting files

Supporting files can be longer than `SKILL.md`, but they should be skimmable:

* use headings
* use stable anchors
* keep links shallow
* avoid deep chains of references

That aligns with Anthropic’s guidance on progressive disclosure, avoiding deeply nested references, and structuring longer reference files so they are easy to navigate. ([Claude][1])

## Minimal template

Example minimal template. Add extra sections only when they actually help.

```md
---
name: <skill-name>
description: <What this does and when to use it. Include likely trigger wording.>
---

# <Skill title>

## Workflow

1. Inspect:
   - `<path/to/file>`
   - `<path/to/test>`
2. Run:
   - `<command or script>`
3. If needed, follow:
   - [Reference material](reference.md)
4. Validate:
   - `<validator command>`
5. If validation fails, fix and rerun.

## Supporting files

- [Reference material](reference.md) — edge cases and deeper rules
- [Examples](examples.md) — realistic examples
- `scripts/<name>` — deterministic helper
- `templates/<name>` — output skeleton
```

This template is meant to embody the upstream guidance: focused scope, strong description, compact main file, progressive disclosure, explicit workflow, and explicit validation. ([Claude][1])

### Optional sections

Only add these when needed:

* `Inputs`
* `Outputs`
* `Stop and report if`
* `Use this skill when`
* `Do not use this skill when`

## Short checklist

Before merging a skill:

* Is the scope narrow?
* Is the description specific and triggerable?
* Is the workflow executable?
* Is validation explicit?
* Did bulky detail move out of `SKILL.md`?
* Should any step be a script instead?
* Are there 2–4 evaluation prompts for routing and behavior?

(This is a compact restatement of the official guidance around scope, descriptions, compactness, scripts, validation, and evaluation. ([Claude][1]))


## Source basis

Main references:

* Anthropic, **Agent Skills overview** — skills as modular capabilities with metadata, instructions, and optional resources loaded progressively. ([Claude][2])
* Anthropic, **Skill authoring best practices** — descriptions, compact `SKILL.md`, progressive disclosure, workflows, validation loops, scripts, and testing. ([Claude][1])
* OpenAI, **Codex best practices** — one skill, one job; clear inputs/outputs; description should say what the skill does and when to use it. ([OpenAI Developers][3])
* OpenAI, **AGENTS.md guide** — `AGENTS.md` as layered project guidance. ([OpenAI Developers][4])
* OpenAI, **Testing Agent Skills Systematically with Evals** — test trigger behavior, process, style, and efficiency. ([OpenAI Developers][5])


[1]: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices "Skill authoring best practices - Claude API Docs"
[2]: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview "Agent Skills - Claude API Docs"
[3]: https://developers.openai.com/codex/learn/best-practices "Best practices – Codex | OpenAI Developers"
[4]: https://developers.openai.com/codex/guides/agents-md "Custom instructions with AGENTS.md – Codex | OpenAI Developers"
[5]: https://developers.openai.com/blog/eval-skills "Testing Agent Skills Systematically with Evals | OpenAI Developers"
