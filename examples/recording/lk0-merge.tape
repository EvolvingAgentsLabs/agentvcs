# VHS tape — LK0 merge, --dry-run, on the CI fixture (no lora-kernel checkout, no model, no Claude Code call).
# Render from the repository root:  vhs examples/recording/lk0-merge.tape
Output "docs/img/lk0-merge-dry-run.gif"

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

Hide
Type "export PYTHON=$PWD/crates/agentvcs-py/.venv/bin/python PS1='$ ' && rm -rf /tmp/lk0 && clear"
Enter
Sleep 500ms
Show

Type "examples/lora-kernel/demo.sh --dry-run --lk examples/lora-kernel/tests/fixture/lk --work /tmp/lk0 \"
Enter
Type `  | sed -n '/^== 3/,/^== 6/p' | grep -v '^     cd ' | sed "s#$HOME#~#g"`
Sleep 600ms
Enter
Sleep 9s
