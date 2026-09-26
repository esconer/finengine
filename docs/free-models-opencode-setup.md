# Free Models Setup on OpenCode — How It Was Done

> Created: 2026-09-26
> Context: oh-my-openagent (OMO) was installed on OpenCode v2.0.18, configured for free-tier `opencode/` models, then uninstalled. This document explains the full setup so it can be reproduced **without the plugin**.

---

## 1. What "free models" means in OpenCode

OpenCode provides built-in models under the `opencode/<model-id>` prefix. Two tiers exist:

| Tier | Prefix | Auth needed | Examples |
|------|--------|-------------|----------|
| **Free** (limited-time, feedback period) | `opencode/` | **No** | `deepseek-v4-flash`, `big-pickle`, `mimo-v2.5`, `longcat-2.0`, `nemotron-3-ultra`, `laguna-s-2.1`, `ling-3.0-tiny`, `north-mini-code`, **`space-bunny-free`**, `longcat-2.5-preview-free` |
| **Zen** (pay-as-you-go) | `opencode/` | Yes (API key + credits) | `gpt-5-nano`, `gpt-5.5`, `claude-fable-5`, `gemini-3.1-pro`, … |

Free models work with **zero configuration** — no API key, no subscription, no `opencode auth login`.

Verify the live catalog anytime:

```powershell
curl.exe -s "https://opencode.ai/zen/go/v1/models" | Select-String "space-bunny"
```

---

## 2. What was installed

**Plugin:** oh-my-openagent 4.19.4 ("Ultimate" edition for OpenCode)
**Installer command used:**

```powershell
bunx oh-my-openagent install --no-tui --platform=opencode `
  --claude=no --gemini=no --copilot=no --openai=no `
  --opencode-zen=no --zai-coding-plan=no --opencode-go=no `
  --kimi-for-coding=no --bailian-coding-plan=no `
  --minimax-cn-coding-plan=no --minimax-coding-plan=no --vercel-ai-gateway=no
```

**Files written by the installer:**

| File | Purpose |
|------|---------|
| `~/.config/opencode/opencode.jsonc` | Added `"oh-my-openagent@latest"` to the `plugin` array |
| `~/.omo/omo.jsonc` | OMO agent → model routing config |

**Manual fix:** The installer skipped ast-grep (`sg`) provisioning. Fixed by:

```powershell
bun add -g @ast-grep/cli
bun pm trust @ast-grep/cli --global
```

---

## 3. How the free-model routing was configured

OMO's config lives in `~/.omo/omo.jsonc` under the `[opencode]` block. Every curated agent and category was pointed at the free model:

```jsonc
// ~/.omo/omo.jsonc
{
  "[opencode]": {
    "$schema": "https://raw.githubusercontent.com/code-yeongyu/oh-my-openagent/dev/assets/omo.schema.json",
    "agents": {
      "hephaestus":         { "model": "opencode/space-bunny-free" },
      "oracle":             { "model": "opencode/space-bunny-free" },
      "librarian":          { "model": "opencode/space-bunny-free" },
      "explore":            { "model": "opencode/space-bunny-free" },
      "multimodal-looker":  { "model": "opencode/space-bunny-free" },
      "prometheus":         { "model": "opencode/space-bunny-free" },
      "metis":              { "model": "opencode/space-bunny-free" },
      "momus":              { "model": "opencode/space-bunny-free" },
      "atlas":              { "model": "opencode/space-bunny-free" },
      "sisyphus-junior":    { "model": "opencode/space-bunny-free" }
    },
    "categories": {
      "visual-engineering": { "model": "opencode/space-bunny-free" },
      "ultrabrain":         { "model": "opencode/space-bunny-free" },
      "deep":               { "model": "opencode/space-bunny-free" },
      "artistry":           { "model": "opencode/space-bunny-free" },
      "quick":              { "model": "opencode/space-bunny-free" },
      "unspecified-low":    { "model": "opencode/space-bunny-free" },
      "unspecified-high":   { "model": "opencode/space-bunny-free" },
      "writing":            { "model": "opencode/space-bunny-free" }
    }
  }
}
```

---

## 4. How to keep free models WITHOUT the plugin

The OMO config file is only read by the OMO plugin. **You do not need the plugin to use free models.** OpenCode itself resolves any `opencode/<model-id>` model directly.

### Option A — Default model in `opencode.jsonc` (simplest)

```jsonc
// ~/.config/opencode/opencode.jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "model": "opencode/space-bunny-free"
}
```

Every new session starts on that model. Switch per-session with the model picker inside OpenCode.

### Option B — Per-agent routing in `opencode.jsonc` (no plugin)

OpenCode v2 supports `[agents]` with model overrides in its own config:

```jsonc
// ~/.config/opencode/opencode.jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "model": "opencode/space-bunny-free",
  "agents": {
    "explore":   { "model": "opencode/space-bunny-free" },
    "librarian": { "model": "opencode/space-bunny-free" },
    "plan":      { "model": "opencode/space-bunny-free" }
  }
}
```

### Option C — Interactive (no file editing)

Inside OpenCode, run `/connect` → pick a provider → choose a login method, or simply `/models` and select `opencode/space-bunny-free`.

---

## 5. Uninstall performed

The plugin was removed after documentation:

1. Removed `"oh-my-openagent@latest"` from the `plugin` array in `~/.config/opencode/opencode.jsonc`
2. Deleted `~/.omo/` (OMO's config directory)
3. Verified `opencode.jsonc` is back to its pre-install state

The `@ast-grep/cli` global package (`sg`) was left installed — it is a standalone CLI, harmless, and useful outside OMO. Remove it with `bun remove -g @ast-grep/cli` if unwanted.

---

## 6. Quick reference

| Task | Command / action |
|------|------------------|
| List free models | `curl.exe -s "https://opencode.ai/zen/go/v1/models"` |
| Check OpenCode version | `opencode --version` |
| Set default model | Edit `model` in `~/.config/opencode/opencode.jsonc` |
| Switch model in-session | Run `/models` in OpenCode TUI |
| Verify plugin health (while installed) | `bunx oh-my-openagent doctor` |
