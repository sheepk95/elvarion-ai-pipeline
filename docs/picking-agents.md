# Picking each agent's model and effort

Rule: **give each agent the lightest model and effort that does its job at full quality.** Not the cheapest that
might work, and not the strongest available. Quality comes first; then spend as little as that quality allows.

Pick for every agent separately, every time: each subagent, reviewer, gate and helper gets its own model and its own
effort, set explicitly. An agent whose effort is left out inherits its parent's, which is how a high-effort chat
quietly burns through a usage window running bulk copying at high effort.

## Model tiers

Most providers have a small fast model, a mid model and a large model. With Claude these are Haiku, Sonnet and Opus.

| Tier | Claude example | Good for |
|---|---|---|
| small | Haiku | bulk mechanical work: copying, counting, watching a log, reformatting |
| mid | Sonnet | most coding, extraction, surveys, testing, second-opinion twins |
| large | Opus | hard design, judgement-heavy code, reviews that decide something, gates |

## Effort classes

| Work | Effort |
|---|---|
| mechanical (copying, tallies, watching) | low |
| crawling, searching, extraction | medium |
| coding, research, plans | medium; high for the harder pieces |
| reviewing | one step above the work it reviews (high for medium work, extra-high for high work) |
| gates, decisions, adversarial checks, adjudication | extra-high |

**Never max.** Extra-high is the top for every agent, reviewer, gate and child chat. Max costs far more; where more
scrutiny is needed, add a fresh extra-high reviewer instead.

**Builders at or below their parent.** A chat spawns builders at or below its own effort. Reviewers may go one step
above the work they review, up to extra-high, even above the parent's effort.

**Decision-makers get full power.** An agent whose output decides a merge, a release, an install or a final
acceptance, or that says something is "safe", runs on the large model at extra-high.

## Escalate instead of over-provisioning

Start routine work at its class default. If a light agent fails, says it is unsure, or its work is rejected for
quality, re-run it **one** step up (more effort, or the next model tier), with its predecessor's transcript or output
as context. After two steps up, the coordinator does the step itself or changes the approach.

A re-run never goes above the parent chat's own effort. At that cap, the next review step fixes the work in place
instead.

## Near the usage limit, pause rather than downgrade

When a usage window is nearly spent, do not swap in weaker agents to squeeze in more work. Finish the step in hand,
write the hand-over note, commit what is green, and pause until the window resets. Work done badly near the limit
costs more to find and redo than the wait.

My working points (tune them to your plan):

- At about 80% of a short window: start no new long agent or gate; checkpoint.
- From about 90% of the weekly allowance: start nothing new.
- At about 96%: pause everything.

## A quick check before you spawn

1. What class is this task (table above)? That sets the starting effort.
2. Does its output decide something? Then large model, extra-high.
3. Is it a review? One step above the work.
4. Are both model and effort written in the call?
5. Is the usage window healthy enough to finish it?
