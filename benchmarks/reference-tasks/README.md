# Reference task suite

This directory contains deterministic, synthetic tasks for comparing ALK
process changes. The suite never launches a model or adapter host.

Each task has a Markdown brief and a versioned JSON oracle. A submission is an
`agent-reference-task-submission.v1` document containing independently produced
ALK receipts. The evaluator records artifact digests and measurements without
storing task or chat transcripts.

The suite covers planning, architecture review, Bug Forensics, bounded S1 work
and evidence-heavy S2 work. These fixtures are regression evidence for ALK
itself; they are not production evidence or a model leaderboard.
