# The lane pipeline brief

This is the brief I pasted into a coordinating chat to set up the pipeline. It was written for the 11 lanes my project
had already been split into; any number of lanes works the same way. The text after the line is kept close to how it
was pasted. [RULES.md](RULES.md) turns it into working mechanics.

---

Here's the simple version written for 11 lanes. Each lane owns its jobs and keeps its builder and reviewer together through the work.

```
11-LANE PIPELINE

You
 ↓
Coordinator
 ↓
11 lanes, each with:
  • One continuing builder
  • One continuing reviewer
  • One fresh final gate reviewer per completed job
 ↓
Integration and relevant player testing
```

At full activity, that means 11 builders and 11 continuing reviewers, plus temporary gate reviewers as jobs reach the final gate. Lanes can work in parallel where the work and available capacity allow; they don't all need to run at once.

You can copy and paste this brief into a coordinating chat:

## 11-lane pipeline

Use this pipeline to coordinate the work across 11 lanes. Keep the structure simple and keep useful context in the builder and reviewer chats.

### Coordinator

The Coordinator:

* Divides work into clear jobs and assigns them to the appropriate lanes.
* Makes sure each job has acceptance criteria before building starts.
* Manages dependencies, capacity and conflicts between lanes.
* Helps resolve repeated problems and arranges a specialist when needed.
* Coordinates integration and player testing when the work is ready.

Run independent lanes in parallel when practical. Avoid starting work that depends on an unfinished decision or conflicts with another active lane.

### Each lane

Each active lane has:

1. One continuing builder, normally at medium reasoning.
2. One continuing reviewer, normally at high reasoning.
3. One fresh gate reviewer for each finished job, normally at extra high reasoning.

The builder and reviewer keep their context through the job, its fixes and its improvement step. They may continue into related jobs while their context remains useful. The final gate reviewer starts fresh for each job.

### The job loop

```
Lane receives job and acceptance criteria
    ↓
Builder plans and builds
    ↓
Reviewer reviews the whole job
    ↓
Reviewer reports:
  • Required fixes
  • Worthwhile improvement opportunities
    ↓
Builder fixes the issues and makes the selected improvement
    ↓
Same reviewer checks the changes and affected areas
    ↓
If issues remain:
  Builder fixes → same reviewer rechecks
    ↓
Fresh gate reviewer checks the whole finished job
    ↓
PASS → ready for integration
FAIL → back to builder and reviewer
```

### Fixes and improvements

Required defects must be addressed before the job passes.

The reviewer must look for up to three worthwhile improvements and recommend the best one. For each, briefly state the expected benefit and effort. Prioritise player-facing improvements when relevant; otherwise consider correctness, performance, maintainability and verification.

The builder should implement the recommended improvement when it fits the job and can be verified without disproportionate extra work. If none is worthwhile, record why rather than making a change for its own sake.

Label the outcome accurately:

* Player-facing improvement: demonstrated through the relevant player flow.
* Performance improvement: measured against a suitable baseline.
* Maintainability improvement: a concrete change that makes the work easier to understand or maintain.
* Verification improvement: stronger tests or evidence.

Where a practical benefit matters, agree on how to measure it before the improvement is made.

### Rechecks and escalation

After fixes or improvements, the same reviewer checks the changed areas and what they affect. If it finds a problem, it sends a specific finding back to the builder.

If an issue remains unresolved after approximately two or three rounds, the lane asks the Coordinator for help. The Coordinator can arrange a higher-effort specialist or decide that the approach needs to change.

Use a specialist when the difficulty justifies it, rather than assigning one to every job.

### Dynamic reasoning

Start routine builder work at medium and reviewer work at high. Increase effort for genuinely difficult work when the available system supports it.

If the system can automatically change the same chat's effort while preserving its context, use that capability. If it cannot, keep the builder's context and bring in a higher-effort specialist with a concise handoff.

Do not claim that effort changed automatically unless the runtime confirms it. Keep helper and reviewer effort at or below extra high.

### Final gate

The fresh gate reviewer checks the whole finished job against its acceptance criteria, including:

* Required behaviour and important edge cases.
* Whether fixes introduced new problems.
* Whether the improvement is useful and supported by evidence.
* Appropriate tests and remaining limitations.

A score can help explain the review, but it does not override a failed acceptance criterion or an unresolved defect.

If the gate fails, send its findings back to the lane. The builder fixes them, the continuing reviewer rechecks the affected work, and a new fresh gate reviews the revised result.

### Integration and player testing

Once a job passes its lane gate, send it to integration with the evidence and any remaining limitations. Run the checks appropriate to the combined work.

For player-facing Unity behaviour, verify the relevant flow using the real keyboard, mouse or applicable device input path. Report code tests, integration checks and observed gameplay separately.
