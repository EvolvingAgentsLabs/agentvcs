# VHS tape — agentvcs running CONTINUOUSLY inside a Claude Code session.
# Install VHS (https://github.com/charmbracelet/vhs):  brew install vhs
# Render (from the repo root):                          vhs examples/recording/cc-continuous.tape
# Output:                                               examples/recording/cc-continuous.gif
#
# Honest by construction: every number below is reconstructed from a REAL captured
# Claude Code session (fixtures/runtime-session.jsonl). This shows the two commands
# Claude Code actually runs once wired — the statusline (every render) and the
# Stop-hook commit (every turn) — not a mock of the TUI.

Output examples/recording/cc-continuous.gif

Set Shell bash
Set FontSize 15
Set Width 1420
Set Height 960
Set Theme "Dracula"
Set TypingSpeed 34ms
Set Padding 26
Set Margin 14
Set MarginFill "#16161e"
Set WindowBar Colorful
Set BorderRadius 10

# --- silent setup: real fixture + runtime repo + two prior checkpoints ---
Hide
Type "source examples/recording/cc_continuous_setup.sh"
Enter
Sleep 2000ms
Show

# 1. wire it once — what Claude Code runs (commented for the viewer)
Type "# ~/.claude/settings.json:  statusLine -> agentvcs statusline   (runs every render)"
Sleep 300ms
Enter
Type "# .claude/settings.json:    Stop hook  -> agentvcs commit        (versions every turn)"
Sleep 300ms
Enter
Sleep 1200ms

# 2. the status line Claude Code paints at the bottom of EVERY turn
Type "agentvcs statusline"
Sleep 400ms
Enter
Sleep 3200ms

# 3. the full frame behind that line — real session, reconstructed
Type "agentvcs runtime"
Sleep 400ms
Enter
Sleep 4500ms

# 4. the Stop hook fires on each turn: the session, committed
Type "agentvcs commit -m 'cc checkpoint: refunds route'"
Sleep 400ms
Enter
Sleep 2800ms

# 5. ...so your session becomes a versioned history of frames
Type "agentvcs log"
Sleep 400ms
Enter
Sleep 5000ms

# clean up the throwaway project + fixture
Hide
Type "cd $ROOT && bash examples/recording/cc_continuous_setup.sh --clean"
Enter
Sleep 600ms
