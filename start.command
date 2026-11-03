#!/bin/sh
# Opens the page: double-click this file in Finder, or run ./start.command.
# Keep the window open while you use the page; closing it stops the page.
cd "$(dirname "$0")" || exit 1
for uv in "$(command -v uv)" "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" \
          /opt/homebrew/bin/uv /usr/local/bin/uv; do
  if [ -x "$uv" ]; then
    "$uv" run ui/server.py "$@"
    code=$?
    # Ctrl-C ends the page with 130. Anything else that is not 0 is an error to read.
    if [ "$code" -ne 0 ] && [ "$code" -ne 130 ]; then
      printf '\nThe page stopped with the error above. Press Return to close this window. '
      read -r _
    fi
    exit "$code"
  fi
done
echo "The page needs uv, which is not installed. Install it with:"
echo
echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"
echo
echo "then open this file again. More at https://docs.astral.sh/uv/"
printf 'Press Return to close this window. '
read -r _
exit 1
