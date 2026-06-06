# VHS tape — renders an authentic GIF of the agent loop straight from run.sh.
# Install VHS (https://github.com/charmbracelet/vhs):  brew install vhs
# Render (from the repo root):                          vhs examples/recording/demo.tape
# Output:                                               examples/recording/demo.gif

Output examples/recording/demo.gif

Set Shell bash
Set FontSize 15
Set Width 1200
Set Height 760
Set Theme "Dracula"
Set TypingSpeed 18ms
Set Padding 20

Type "bash examples/agent-loop-demo/run.sh"
Sleep 600ms
Enter
Sleep 9s
