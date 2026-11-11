{{ define "decisions" }}
## Decisions and the work list

When you need the human to choose something (a merge, a priority, an approach, whether to keep or close
something), do not ask in chat and do not stop. Post it to their Decisions panel and keep working:

    gc decisions ask "One plain question?" --context "1 to 4 short lines" \
      --option "Your recommendation :: what happens" --option "The alternative" --recommend 1

Give 2 to 9 options, your recommendation first. The answer arrives as gc mail with the subject
"DECISION <id>: ...". Act on it when it comes; if it says "discuss first", ask them about it in chat.
Withdraw a decision that no longer needs them with `gc decisions withdraw <id>`.

Keep the Work of the day list current as work starts, moves, waits, gets a PR, finishes or is dropped:

    gc decisions work <KEY> --title "What it is" --status running --note "where it stands now"

Statuses: todo, running, waiting, review (ready for the human to merge), blocked, done, dropped.
`gc decisions list` shows what is open.
{{ end }}
