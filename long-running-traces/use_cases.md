## Root cause correlation from “end user → database → infrastructure”
They explicitly want visibility and correlation that answers: “the reason that application went down is X” and care about seeing front-end to DB and back, while also tying in infra/network signals.

## Operational visibility for a critical nightly batch chain (end-of-day close)
They run a nightly batch process to close daily trades/portfolio activity and want to monitor each step’s completion time, detect lateness early, and understand how delays cascade to downstream steps—today handled by scripts/in-house monitors that they want to modernize/centralize.