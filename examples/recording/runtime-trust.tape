# VHS tape — records a REAL run of the runtime-visibility layer + the trust loop.
# Install VHS (https://github.com/charmbracelet/vhs):  brew install vhs
# Render (from the repo root):                          vhs examples/recording/runtime-trust.tape
# Output:                                               examples/recording/runtime-trust.gif

Output examples/recording/runtime-trust.gif

Set Shell bash
Set FontSize 15
Set Width 1380
Set Height 940
Set Theme "Dracula"
Set TypingSpeed 36ms
Set Padding 26
Set Margin 14
Set MarginFill "#16161e"
Set WindowBar Colorful
Set BorderRadius 10

# --- silent setup: seeds a real session transcript + a buggy add(), inits, commits ---
Hide
Type "source examples/recording/runtime_setup.sh"
Enter
Sleep 2000ms
Show

# 1. THE HEADLINE — the operational frame your runtime keeps to itself, from a real
#    session log: dollars spent, context %, model routing, real tool usage.
Type "agentvcs runtime"
Sleep 400ms
Enter
Sleep 5500ms

# 2. the trust gate — a frozen recipe must be PROVEN. add() is buggy, so freeze refuses.
Type "agentvcs freeze"
Sleep 400ms
Enter
Sleep 3200ms

# 3. fix the bug in the open
Type "printf 'def add(a, b):\n    return a + b\n' > app.py"
Sleep 300ms
Enter
Sleep 800ms

# 4. prove it — the eval passes now
Type "agentvcs commit -m 'fix add()' && agentvcs eval"
Sleep 400ms
Enter
Sleep 3200ms

# 5. now freeze succeeds and the recipe is stamped verified
Type "agentvcs freeze -m 'freeze verified add()'"
Sleep 400ms
Enter
Sleep 3200ms

# 6. the cache reflex — recall the verified recipe to replay instead of re-deriving
Type "agentvcs recall 'add function'"
Sleep 400ms
Enter
Sleep 5000ms

# clean up the throwaway project + seeded transcript (cwd is inside the demo now)
Hide
Type "cd $ROOT && bash examples/recording/runtime_setup.sh --clean"
Enter
Sleep 600ms
