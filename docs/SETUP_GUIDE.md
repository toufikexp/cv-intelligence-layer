# CV Intelligence Layer — AI Coding Agent Setup Guide

## How Claude Code and Cursor discover context differently

Understanding this difference is key to placing files correctly.

**Claude Code** reads `CLAUDE.md` at the start of every session — that's your one shot at persistent context. Everything else is discovered on demand: Claude reads files when it needs them, and you can point it to files with `@filename`. The instruction budget is limited (~150-200 instructions total including system prompt), so CLAUDE.md must be lean. Detail goes in separate files that Claude reads when working on that specific area.

**Cursor** uses `.cursor/rules/*.mdc` files that are glob-scoped — each rule file activates only when you're editing files matching its pattern. This means you can have rich, specific context per file type without bloating the context window. The old `.cursorrules` single file is deprecated.

---

## Use Case 1: Claude Code

### File placement

```
cv-intelligence-layer/
├── CLAUDE.md                          ← AUTO-LOADED every session
├── SPEC.md                            ← Full spec, read on demand via @SPEC.md
├── .claude/
│   ├── commands/
│   │   ├── implement.md               ← /implement slash command
│   │   └── review.md                  ← /review slash command
│   └── skills/
│       ├── cv-extraction.md           ← On-demand skill for extraction work
│       └── cv-ranking.md              ← On-demand skill for ranking work
├── prompts/
│   ├── cv_entity_extraction.md        ← LLM prompt template (loaded by app code)
│   ├── cv_ranking.md                  ← LLM prompt template
│   └── answer_scoring.md              ← LLM prompt template
├── schemas/
│   ├── candidate_profile.json         ← JSON Schema for validation
│   └── openapi_cv_layer.yaml          ← Full API contract
└── docs/
    └── solution_architecture.md       ← Architecture reference
```

### Why this layout works

**CLAUDE.md (< 120 lines)**: Lean by design. Contains the "what, how, and critical rules" — just enough for Claude to understand the project and avoid mistakes. Does NOT contain the full spec, database schema, or API details. Instead, it uses progressive disclosure with `@` references:

```markdown
## Key references (read on demand, don't memorize)
- Full spec: `@SPEC.md`
- LLM prompts: `@prompts/cv_entity_extraction.md`
- Data model: `@schemas/candidate_profile.json`
```

This keeps CLAUDE.md under the instruction budget while giving Claude a map to find everything.

**SPEC.md**: The detailed specification document. Claude reads this when it needs specifics — pipeline stages, database schema, scoring formulas, env vars. Placing it at the project root makes it easy to reference with `@SPEC.md`.

**`.claude/commands/`**: Custom slash commands you invoke explicitly:
- `/implement document_processor` — triggers the implement workflow with the argument
- `/review` — runs a comprehensive code review checklist

**`.claude/skills/`**: On-demand knowledge loaded when Claude detects it's relevant (or you explicitly ask). The skill files contain domain-specific rules and patterns that would bloat CLAUDE.md if included there.

### Recommended workflow

#### Step 1: Initial project setup
```bash
cd cv-intelligence-layer
# Place all the files from the claude-code package
claude  # Start Claude Code
```

Claude auto-reads CLAUDE.md. Then:

```
> Read @SPEC.md and set up the initial project structure — pyproject.toml, 
> Docker files, alembic config, and empty module files matching the structure 
> in CLAUDE.md. Don't implement business logic yet.
```

#### Step 2: Interview-driven specification (recommended)
```
> I want to build the Document Processor component. Interview me using 
> AskUserQuestion about edge cases, OCR behavior, and error handling. 
> Then update SPEC.md with what we decide.
```

This is a Claude Code superpower — the interview approach lets Claude dig into hard parts you might not have considered, producing a more complete spec before any code is written.

#### Step 3: Implement component by component
```
> /implement document_processor — the PDF/DOCX text extraction service
```

The `/implement` command reads the spec, relevant prompt files, and schemas before writing code.

#### Step 4: Review
```
> /review
```

Runs architecture checks, type checking, linting, and tests.

#### Step 5: Compact and continue
At ~50% context usage, manually run `/compact` to keep Claude sharp. Add instructions for what to preserve:
```
> /compact Focus on the services we've built so far and the test results
```

### Pro tips for Claude Code

1. **Two-session pattern**: Session A implements the feature. Start a fresh Session B to review it — the reviewer has no knowledge of implementation shortcuts and will challenge every one of them.

2. **Keep CLAUDE.md under 120 lines**. For every line, ask: would Claude make a mistake without this? If Claude already does something correctly on its own, the instruction is noise.

3. **Use `@` references** instead of embedding content. `@schemas/openapi_cv_layer.yaml` loads the file on demand rather than bloating every session.

4. **Skills over CLAUDE.md for domain knowledge**. The OCR pipeline details and ranking formulas are in `.claude/skills/` — they load only when Claude is working on those areas, saving context for the actual coding.

5. **Run `/init` after initial setup** to let Claude refine your CLAUDE.md based on the actual codebase structure.

---

## Use Case 2: Cursor AI

### File placement

```
cv-intelligence-layer/
├── .cursor/
│   └── rules/
│       ├── project.mdc                ← alwaysApply: true (core rules)
│       ├── api-routes.mdc             ← globs: app/api/**/*.py
│       ├── services.mdc               ← globs: app/services/**/*.py
│       ├── celery-tasks.mdc           ← globs: app/tasks/**/*.py
│       └── llm-prompts.mdc            ← globs: prompts/**/*.md
├── SPEC.md                            ← Full spec (reference with @SPEC.md)
├── prompts/
│   ├── cv_entity_extraction.md
│   ├── cv_ranking.md
│   └── answer_scoring.md
├── schemas/
│   ├── candidate_profile.json
│   └── openapi_cv_layer.yaml
└── docs/
    └── solution_architecture.md
```

### Why this layout works

**`.cursor/rules/project.mdc` (alwaysApply: true)**: This is your equivalent of CLAUDE.md — it loads on every interaction. Contains the core architecture rules, tech stack, and code style. Kept concise.

**Glob-scoped `.mdc` files**: This is Cursor's advantage. Each rule file activates ONLY when you're editing files matching its glob pattern:

- `api-routes.mdc` → activates when editing `app/api/*.py` → provides handler patterns, auth rules, response format
- `services.mdc` → activates when editing `app/services/*.py` → provides integration patterns, client rules
- `celery-tasks.mdc` → activates when editing `app/tasks/*.py` → provides idempotency rules, retry patterns
- `llm-prompts.mdc` → activates when editing `prompts/*.md` → provides prompt structure rules

This means when you're working on a Celery task, Cursor gets the core rules PLUS the specific Celery guidance — without loading API route rules that aren't relevant.

**No `.cursorrules` file**: The legacy `.cursorrules` root file is still supported but deprecated. Migrate to the new `.mdc`-based Project Rules for full functionality.

### Recommended workflow

#### Step 1: Initial setup
Place all files from the cursor package in your project root. Open the project in Cursor.

#### Step 2: Use Agent Mode for scaffolding
Press `Cmd+.` (or `Ctrl+.`) to toggle Agent Mode, then:

```
Read @SPEC.md and scaffold the full project structure. Create pyproject.toml 
with all dependencies, Docker files, alembic config, and empty module files.
Reference @schemas/openapi_cv_layer.yaml for the API endpoints to create.
```

Agent Mode auto-pulls context and can execute commands — it'll create files, install deps, and run setup.

#### Step 3: Implement with context-aware rules
When you open `app/services/document_processor.py` and start typing in Cursor, it automatically loads:
- `project.mdc` (always)
- `services.mdc` (matches `app/services/**/*.py`)

So the AI knows both the core architecture rules AND the specific service-layer patterns.

```
Implement the DocumentProcessor service. It should extract text from PDF 
(PyMuPDF) and DOCX (python-docx) files. Reference @prompts/cv_entity_extraction.md 
for what the extracted text will be used for. Route to OCR if text < 50 chars/page.
```

#### Step 4: Use @-references for deep context
Cursor supports `@file` references in chat. Use them to pull in specific specs:

```
Implement the ranking endpoint. Reference @schemas/openapi_cv_layer.yaml 
for the request/response schema and @prompts/cv_ranking.md for the LLM 
scoring template.
```

### Pro tips for Cursor

1. **Split rules by concern, not by size**. If your rules file gets bloated, split it into context-aware `.mdc` files. This reduces token usage by only activating relevant rules when needed.

2. **Use `@` references liberally**. Point Cursor at `@SPEC.md`, `@schemas/openapi_cv_layer.yaml`, and specific prompt files when working on related code.

3. **Add a `.cursorignore`** to exclude noise:
   ```
   __pycache__/
   .mypy_cache/
   *.pyc
   /data/uploads/
   ```
   Use `.cursorignore` to exclude files from indexing. This prevents Cursor from loading unnecessary files into context.

4. **Agent Mode for multi-file changes**. When implementing a new endpoint (schema + route + service + test), use Agent Mode — it handles cross-file edits better than inline completions.

5. **Version control the rules**. Since rules are stored in `.cursor/rules`, they're automatically version-controlled, so the whole team gets the same AI behavior.

---

## Key differences: which to choose when

| Aspect | Claude Code | Cursor |
|--------|-------------|--------|
| **Context loading** | CLAUDE.md always + on-demand `@` refs | Glob-scoped `.mdc` auto-attach |
| **Best for** | Greenfield scaffolding, complex multi-file tasks, review workflows | Incremental implementation, file-by-file editing |
| **Custom workflows** | Slash commands + skills | Agent Mode + rule scoping |
| **Context management** | Manual `/compact` at 50% | Automatic per-rule scoping |
| **Two-session review** | Native pattern (fresh context) | Possible but less natural |
| **Interview-driven spec** | Built-in AskUserQuestion tool | Not built-in |
| **Terminal integration** | IS the terminal | IDE with embedded terminal |

### My recommendation for this project

**Start with Claude Code** to scaffold the project structure, write the initial services, and iterate on the spec via the interview pattern. Claude Code excels at the early "figure out the architecture and write the first implementation" phase.

**Switch to Cursor** for day-to-day development once the structure is in place. Cursor's glob-scoped rules shine when you're editing specific files and want context-aware suggestions without managing context manually.

Both setups use the same `prompts/`, `schemas/`, and `SPEC.md` files — the only difference is the instruction layer on top (CLAUDE.md + commands/skills vs `.cursor/rules/*.mdc`).
