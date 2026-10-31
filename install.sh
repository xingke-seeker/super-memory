#!/usr/bin/env bash
# super-memory 一键安装：venv + CLI + harness 集成（skill + 全局协议）+ launchd 定时消化
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
WITH_LAUNCHD=1
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
OPENCODE_CONFIG_HOME="${OPENCODE_CONFIG_HOME:-${XDG_CONFIG_HOME:-$HOME/.config}/opencode}"
KIMI_CODE_HOME="${KIMI_CODE_HOME:-$HOME/.kimi-code}"
CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
TRAE_HOME="${TRAE_HOME:-$([[ -d "$HOME/.trae-cn" ]] && echo "$HOME/.trae-cn" || echo "$HOME/.trae")}"
DSH_HOME="${DSH_HOME:-$HOME/.dsh}"
HARNESSES=()

for arg in "$@"; do
    case "$arg" in
        --no-launchd) WITH_LAUNCHD=0 ;;
        --harness=*) HARNESSES+=("${arg#--harness=}") ;;
        --harness)
            echo "用法: ./install.sh [--no-launchd] [--harness codex|opencode|kimi|claude|trae|dsh|all]（--harness 需要 =值 形式）" >&2
            exit 2 ;;
        -h|--help)
            echo "usage: ./install.sh [--no-launchd] [--harness codex|opencode|kimi|claude|trae|dsh|all]"
            echo "  --no-launchd    只安装 CLI 与 harness 集成，不注册 6 小时定时消化任务"
            echo "  --harness       安装目标 harness，可重复传；缺省 all = 对本机检测到的 harness 全部安装"
            exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

step() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

want_codex=0
want_opencode=0
want_kimi=0
want_claude=0
want_trae=0
want_dsh=0
if [[ ${#HARNESSES[@]} -eq 0 || " ${HARNESSES[*]} " == *" all "* ]]; then
    [[ -d "$CODEX_HOME" || -n "${CODEX_BIN:-}" || -x /Applications/ChatGPT.app/Contents/Resources/codex ]] \
        && want_codex=1 || true
    { [[ -d "$OPENCODE_CONFIG_HOME" ]] || command -v opencode >/dev/null 2>&1; } \
        && want_opencode=1 || true
    { [[ -d "$KIMI_CODE_HOME" ]] || command -v kimi >/dev/null 2>&1; } \
        && want_kimi=1 || true
    { [[ -d "$CLAUDE_CONFIG_DIR" ]] || command -v claude >/dev/null 2>&1; } \
        && want_claude=1 || true
    { [[ -d "$TRAE_HOME" ]] || [[ -x "/Applications/Trae.app/Contents/MacOS/Trae" ]] || [[ -x "/Applications/Trae CN.app/Contents/MacOS/Trae CN" ]]; } \
        && want_trae=1 || true
    { [[ -d "$DSH_HOME" ]] || command -v dsh >/dev/null 2>&1; } \
        && want_dsh=1 || true
else
    for h in "${HARNESSES[@]}"; do
        case "$h" in
            codex) want_codex=1 ;;
            opencode) want_opencode=1 ;;
            kimi) want_kimi=1 ;;
            claude) want_claude=1 ;;
            trae) want_trae=1 ;;
            dsh) want_dsh=1 ;;
            *) echo "unknown harness: $h（可选 codex|opencode|kimi|claude|trae|dsh|all）" >&2; exit 2 ;;
        esac
    done
fi
if [[ $want_codex -eq 0 && $want_opencode -eq 0 && $want_kimi -eq 0 && $want_claude -eq 0 && $want_trae -eq 0 && $want_dsh -eq 0 ]]; then
    echo "未检测到 codex、opencode、Kimi Code、Claude Code、Trae 或 dsh，没有可安装的 harness" >&2
    exit 1
fi

# 1. venv + CLI
step "安装 Python 包到 $REPO_DIR/.venv"
if [[ ! -x "$REPO_DIR/.venv/bin/supermemory" ]]; then
    "$PYTHON" -m venv "$REPO_DIR/.venv"
    "$REPO_DIR/.venv/bin/pip" install -q -e "$REPO_DIR"
else
    "$REPO_DIR/.venv/bin/pip" install -q -e "$REPO_DIR"
fi
SM="$REPO_DIR/.venv/bin/supermemory"
"$SM" --help >/dev/null

# 2. codex 集成（skill + AGENTS.md 协议 + config.toml 沙箱放行）
if [[ $want_codex -eq 1 ]]; then
    step "安装 codex skill 到 $CODEX_HOME/skills/super-memory/"
    mkdir -p "$CODEX_HOME/skills/super-memory"
    sed "s|@SUPERMEMORY_CLI@|$SM|g" "$REPO_DIR/codex/SKILL.md" > "$CODEX_HOME/skills/super-memory/SKILL.md"

    step "写入 $CODEX_HOME/AGENTS.md 记忆协议块"
    SNIPPET="$(sed "s|@SUPERMEMORY_CLI@|$SM|g" "$REPO_DIR/codex/AGENTS.snippet.md")"
    AGENTS="$CODEX_HOME/AGENTS.md"
    touch "$AGENTS"
    if grep -q '<!-- super-memory:start -->' "$AGENTS"; then
        awk '/<!-- super-memory:start -->/{skip=1} /<!-- super-memory:end -->/{skip=0; next} !skip' "$AGENTS" > "$AGENTS.tmp"
        mv "$AGENTS.tmp" "$AGENTS"
    fi
    printf '\n%s\n' "$SNIPPET" >> "$AGENTS"

    # 幂等；避免记忆写入触发 auto_review 审批 503。失败不阻断安装
    step "配置 $CODEX_HOME/config.toml：沙箱直接可写 $HOME/.super-memory"
    if ! "$REPO_DIR/.venv/bin/python" "$REPO_DIR/scripts/codex_config.py" install \
            --codex-home "$CODEX_HOME" --memory-dir "$HOME/.super-memory"; then
        echo "警告: config.toml 自动配置失败，请按上面提示手动加入 writable_roots" >&2
    fi
fi

# 3. opencode 集成（skill + AGENTS.md 协议；opencode 无需 config 改动）
if [[ $want_opencode -eq 1 ]]; then
    step "安装 opencode skill 到 $OPENCODE_CONFIG_HOME/skills/super-memory/"
    mkdir -p "$OPENCODE_CONFIG_HOME/skills/super-memory"
    sed "s|@SUPERMEMORY_CLI@|$SM|g" "$REPO_DIR/opencode/SKILL.md" > "$OPENCODE_CONFIG_HOME/skills/super-memory/SKILL.md"

    step "写入 $OPENCODE_CONFIG_HOME/AGENTS.md 记忆协议块"
    SNIPPET="$(sed "s|@SUPERMEMORY_CLI@|$SM|g" "$REPO_DIR/opencode/AGENTS.snippet.md")"
    AGENTS="$OPENCODE_CONFIG_HOME/AGENTS.md"
    touch "$AGENTS"
    if grep -q '<!-- super-memory:start -->' "$AGENTS"; then
        awk '/<!-- super-memory:start -->/{skip=1} /<!-- super-memory:end -->/{skip=0; next} !skip' "$AGENTS" > "$AGENTS.tmp"
        mv "$AGENTS.tmp" "$AGENTS"
    fi
    printf '\n%s\n' "$SNIPPET" >> "$AGENTS"
fi

# 4. Kimi Code 集成（skill + AGENTS.md 协议；无需 config 改动）
if [[ $want_kimi -eq 1 ]]; then
    step "安装 Kimi Code skill 到 $KIMI_CODE_HOME/skills/super-memory/"
    mkdir -p "$KIMI_CODE_HOME/skills/super-memory"
    sed "s|@SUPERMEMORY_CLI@|$SM|g" "$REPO_DIR/kimi/SKILL.md" > "$KIMI_CODE_HOME/skills/super-memory/SKILL.md"

    step "写入 $KIMI_CODE_HOME/AGENTS.md 记忆协议块"
    SNIPPET="$(sed -e "s|@SUPERMEMORY_CLI@|$SM|g" -e "s|@KIMI_CODE_HOME@|$KIMI_CODE_HOME|g" "$REPO_DIR/kimi/AGENTS.snippet.md")"
    AGENTS="$KIMI_CODE_HOME/AGENTS.md"
    touch "$AGENTS"
    if grep -q '<!-- super-memory:start -->' "$AGENTS"; then
        awk '/<!-- super-memory:start -->/{skip=1} /<!-- super-memory:end -->/{skip=0; next} !skip' "$AGENTS" > "$AGENTS.tmp"
        mv "$AGENTS.tmp" "$AGENTS"
    fi
    printf '\n%s\n' "$SNIPPET" >> "$AGENTS"
fi

# 5. Claude Code 集成（skill + CLAUDE.md 协议；无需 settings 改动）
if [[ $want_claude -eq 1 ]]; then
    step "安装 Claude Code skill 到 $CLAUDE_CONFIG_DIR/skills/super-memory/"
    mkdir -p "$CLAUDE_CONFIG_DIR/skills/super-memory"
    sed "s|@SUPERMEMORY_CLI@|$SM|g" "$REPO_DIR/claude/SKILL.md" > "$CLAUDE_CONFIG_DIR/skills/super-memory/SKILL.md"

    step "写入 $CLAUDE_CONFIG_DIR/CLAUDE.md 记忆协议块"
    SNIPPET="$(sed -e "s|@SUPERMEMORY_CLI@|$SM|g" -e "s|@CLAUDE_CONFIG_DIR@|$CLAUDE_CONFIG_DIR|g" "$REPO_DIR/claude/CLAUDE.snippet.md")"
    AGENTS="$CLAUDE_CONFIG_DIR/CLAUDE.md"
    touch "$AGENTS"
    if grep -q '<!-- super-memory:start -->' "$AGENTS"; then
        awk '/<!-- super-memory:start -->/{skip=1} /<!-- super-memory:end -->/{skip=0; next} !skip' "$AGENTS" > "$AGENTS.tmp"
        mv "$AGENTS.tmp" "$AGENTS"
    fi
    printf '\n%s\n' "$SNIPPET" >> "$AGENTS"
fi

# 6. Trae 集成（skill + skill-config.json 注册；Trae 无用户级全局指令文件，靠 skill 触发词召回）
if [[ $want_trae -eq 1 ]]; then
    step "安装 Trae skill 到 $TRAE_HOME/skills/super-memory/"
    mkdir -p "$TRAE_HOME/skills/super-memory"
    sed "s|@SUPERMEMORY_CLI@|$SM|g" "$REPO_DIR/trae/SKILL.md" > "$TRAE_HOME/skills/super-memory/SKILL.md"

    step "在 $TRAE_HOME/skill-config.json 登记 super-memory skill"
    if ! "$REPO_DIR/.venv/bin/python" "$REPO_DIR/scripts/trae_skill_config.py" install \
            --trae-home "$TRAE_HOME"; then
        echo "警告: skill-config.json 自动登记失败，请在 Trae 的技能设置中手动启用 super-memory" >&2
    fi
fi

# 7. dsh (deepseek-harness) 集成（skill + AGENTS.md 协议；无需 config 改动）
if [[ $want_dsh -eq 1 ]]; then
    step "安装 dsh skill 到 $DSH_HOME/skills/super-memory/"
    mkdir -p "$DSH_HOME/skills/super-memory"
    sed "s|@SUPERMEMORY_CLI@|$SM|g" "$REPO_DIR/dsh/SKILL.md" > "$DSH_HOME/skills/super-memory/SKILL.md"

    step "写入 $DSH_HOME/AGENTS.md 记忆协议块"
    SNIPPET="$(sed -e "s|@SUPERMEMORY_CLI@|$SM|g" -e "s|@DSH_HOME@|$DSH_HOME|g" "$REPO_DIR/dsh/AGENTS.snippet.md")"
    AGENTS="$DSH_HOME/AGENTS.md"
    touch "$AGENTS"
    if grep -q '<!-- super-memory:start -->' "$AGENTS"; then
        awk '/<!-- super-memory:start -->/{skip=1} /<!-- super-memory:end -->/{skip=0; next} !skip' "$AGENTS" > "$AGENTS.tmp"
        mv "$AGENTS.tmp" "$AGENTS"
    fi
    printf '\n%s\n' "$SNIPPET" >> "$AGENTS"
fi

# 8. launchd 定时消化（仅 macOS；worker 支持 codex/opencode/Kimi Code/Claude Code/dsh，无 Trae）
if [[ "$WITH_LAUNCHD" -eq 1 ]]; then
    if [[ "$(uname)" != "Darwin" ]]; then
        step "非 macOS，跳过 launchd（可用 cron 代替：每 6 小时执行 $REPO_DIR/scripts/digest.sh）"
    elif [[ $want_codex -eq 0 && $want_opencode -eq 0 && $want_kimi -eq 0 && $want_claude -eq 0 && $want_dsh -eq 0 ]] \
            && ! { command -v codex >/dev/null 2>&1 || command -v opencode >/dev/null 2>&1 \
            || command -v kimi >/dev/null 2>&1 || command -v claude >/dev/null 2>&1 \
            || command -v dsh >/dev/null 2>&1 \
            || [[ -x /Applications/ChatGPT.app/Contents/Resources/codex ]]; }; then
        step "仅安装 Trae：本机无无人值守 worker CLI，跳过 launchd 定时消化"
        echo "  （在 Trae 会话内说「消化积压」触发蒸馏，或手动运行 $SM pending / apply）"
    else
        step "注册 launchd 定时消化（每 6 小时）"
        PLIST="$HOME/Library/LaunchAgents/com.supermemory.digest.plist"
        mkdir -p "$HOME/Library/LaunchAgents" "$HOME/.super-memory"
        sed -e "s|@REPO_DIR@|$REPO_DIR|g" -e "s|@HOME@|$HOME|g" \
            -e "s|@KIMI_CODE_HOME@|$KIMI_CODE_HOME|g" \
            -e "s|@CLAUDE_CONFIG_DIR@|$CLAUDE_CONFIG_DIR|g" \
            -e "s|@TRAE_HOME@|$TRAE_HOME|g" \
            "$REPO_DIR/scripts/com.supermemory.digest.plist" > "$PLIST"
        chmod +x "$REPO_DIR/scripts/digest.sh" "$REPO_DIR/scripts/digest_codex.sh" "$REPO_DIR/scripts/digest_opencode.sh" "$REPO_DIR/scripts/digest_kimi.sh" "$REPO_DIR/scripts/digest_claude.sh" "$REPO_DIR/scripts/digest_dsh.sh"
        launchctl bootout "gui/$(id -u)/com.supermemory.digest" 2>/dev/null || true
        launchctl bootstrap "gui/$(id -u)" "$PLIST"
    fi
fi

step "安装完成"
"$SM" status || true
cat <<EOF

接下来：
  - 正常使用已安装的 harness（codex / opencode / Kimi Code / Claude Code / Trae / dsh）即可：新会话开始非平凡任务时会自动召回记忆并消化积压
  - Trae 无全局指令机制，召回靠 skill 触发词（记忆 / 之前我们 / 消化积压…）；若新装的 skill 未生效，完全重启 Trae 后在技能设置中确认 super-memory 已启用
  - 手动触发一次消化（默认最多 50 个会话）: $REPO_DIR/scripts/digest.sh
  - 首次构建记忆且历史会话较多时，可调大单次上限: $REPO_DIR/scripts/digest.sh --max-sessions 500
  - 口令触发: 在 harness 里说「消化积压」「沉淀记忆」「记住: ...」
  - 卸载: $REPO_DIR/uninstall.sh
EOF
