# VHS tape — records a REAL run of the Claude Code trace provider.
# Install VHS (https://github.com/charmbracelet/vhs):  brew install vhs
# Render (from the repo root):                          vhs examples/recording/cc-trace.tape
# Output:                                               examples/recording/cc-trace.gif

Output examples/recording/cc-trace.gif

Set Shell bash
Set FontSize 15
Set Width 1380
Set Height 860
Set Theme "Dracula"
Set TypingSpeed 38ms
Set Padding 26
Set Margin 14
Set MarginFill "#16161e"
Set WindowBar Colorful
Set BorderRadius 10

# --- silent setup: builds the toy project, seeds the session transcript, inits ---
Hide
Type "source examples/recording/cc_trace_setup.sh"
Enter
Sleep 1800ms
Show

# 1. the wiring: trace is a provider (the live session), model is auto-detected
Type "cat agent.json"
Sleep 400ms
Enter
Sleep 3200ms

# 2. confirm which session is hooked (message count + model) BEFORE committing
Type "agentvcs trace"
Sleep 400ms
Enter
Sleep 3200ms

# 3. commit — captures the live conversation, zero trace file to maintain
Type "agentvcs commit -m 'v1: triage queue'"
Sleep 400ms
Enter
Sleep 2600ms

# 4. the payoff — code + the EXACT conversation that produced it, on a clean screen
Type "clear"
Enter
Sleep 300ms
Type "agentvcs show --trace"
Sleep 400ms
Enter
Sleep 6000ms
