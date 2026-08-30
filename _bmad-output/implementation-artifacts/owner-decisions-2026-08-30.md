# Owner decisions — wave of 2026-08-30

Rulings given by the owner on findings the review lanes correctly refused to
decide for themselves. A lane implements the ruling for its own story, records
it in the spec's change log as an owner decision (dated 2026-08-30), and adds
the regression that proves it.

## 1. Story 7.1 — pyannote telemetry (review finding 5)

**Ruling: disable it.**

AD-12 permits egress, so this was a policy choice, not a defect. The engine
must not phone home: disable the library's telemetry/analytics at
construction (not by documentation alone), and pin it with a test that fails
if the disabling call is removed. Record the choice in the spec and in the
operator-facing wording beside the engine's other settings.

## 2. Story 10.1 — topic parser acceptance boundary (review finding 5)

**Ruling: fairly strict.**

Heading drift stays tolerated (`## Discussion themes` and the like), but a
document must look like a topics document before any `T`-row becomes a topic:
require topic semantics in the heading or the table shape (Topic/Gist columns)
as the reviewer proposed. A contentful foreign table — `## Decisions`,
`## Notes`, a task list — must fail by name and earn the generate-path retry
rather than persisting a false topic. Keep the header-only shared case as an
honest zero. Regressions both ways: the accepted drift case, and a rejected
Decisions/Tasks table.

## 3. Story 10.1 — orphan topics after a moment cascade (review finding 9)

**Ruling: delete the topic.**

One invariant, enforced across stage boundaries: a topic with no surviving
mention does not exist. When a moment cascade removes a topic's last mention,
the topic goes with it — at the database level, so the rule holds no matter
which stage or transaction did the deleting (an augmentation that re-arms
`moments` while leaving `extract` settled included). Replace the test that
pins topic-with-zero-mentions as acceptable, and add the integration
regression the reviewer asked for: an augmentation that removes the sole
mentioned moment, with `extract` left settled, leaves no topic behind.
