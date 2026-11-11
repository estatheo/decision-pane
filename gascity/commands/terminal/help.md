Show Decisions and Work in an interactive terminal, including a tmux split.

Usage: gc decisions terminal [--city /path/to/city]

Keys: 1-9 choose, e write an answer, d discuss first, l later, r refresh or
retry delivery, j/k scroll, w toggle finished work, q quit. While writing:
Enter sends, Esc leaves editing. Requires Python curses (macOS/Linux).

Option rows and bracketed controls also accept clicks. Use Up/Down to scroll;
wheel support depends on the terminal's curses build.
Enable tmux mouse for your session to click into panes and drag the divider:
tmux set-option -t <session-name> mouse on
