Put a decision in the human's Decisions panel instead of asking in chat.

  gc decisions ask "Merge the auth refactor now or after the release?" \
    --context "Tests pass. The release branch is cut on Friday." \
    --option "Merge now :: lands in this release" \
    --option "Wait for the release" \
    --recommend 1

The answer comes back to you as gc mail whose subject starts "DECISION <id>:".
Keep working on other things meanwhile.
