anki add-on

### For compressing (if modifying)

1. Run `Get-ChildItem -Path . -Recurse -Exclude "__pycache__", "*.pyc" | >> Compress-Archive -DestinationPath ../syntax_highlighter.zip -Forceclear` in `/syntax_highlighter`
2. Change .zip extension to .ankiaddon
