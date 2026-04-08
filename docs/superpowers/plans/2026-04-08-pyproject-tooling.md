# pyproject.toml Tooling Configuration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete `pyproject.toml` with target-version pins, expanded ruff rules, and pytest configuration.

**Architecture:** Single-file edit — add 6 settings to the existing `pyproject.toml`. No new files. No code changes required unless B/UP rules flag existing code.

**Tech Stack:** ruff, black, pytest (all already installed)

---

## Chunk 1: Update pyproject.toml and verify the gate

### Task 1: Update pyproject.toml

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Replace `pyproject.toml` with the complete configuration**

The final file should contain exactly:

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
addopts = "--tb=short"

[tool.black]
line-length = 100
target-version = ["py311"]

[tool.ruff]
line-length = 100
target-version = "py311"
src = ["."]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP"]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["B011"]
```

- [ ] **Step 2: Run ruff**

```bash
ruff check .
```

Expected: no output (zero findings). If B or UP rules flag anything, fix the flagged lines before proceeding. Common fixes:
- UP006/UP007: replace `List[X]` → `list[X]`, `Optional[X]` → `X | None`
- B006: replace mutable default argument with `field(default_factory=...)`

- [ ] **Step 3: Run black**

```bash
black --check .
```

Expected: `All done! ✨ 🍰 ✨` with no reformatted files. If black wants to reformat anything, run `black .` to apply, then re-check.

- [ ] **Step 4: Run pytest**

```bash
pytest
```

Expected: `31 passed` (all existing tests pass with new pytest config). Confirm `testpaths` and `addopts` take effect — output should show short tracebacks and auto-discover `tests/`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "chore: complete pyproject.toml with target-version, bugbear, pyupgrade, testpaths"
```
