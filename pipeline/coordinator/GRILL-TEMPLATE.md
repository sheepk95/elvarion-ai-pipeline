# GRILL-<n>: <lane>-<n> <job title>

Step 0 of every new card (JOB-TEMPLATE.md 'Step 0: GRILL'). The builder writes this file at
`jobs/<lane>-<n>/GRILL-<n>.md` before building. List ONLY the design questions that the card, the lane's scorecard and
the owner's past answers do not already settle. Then send ONE Q item to `coordinator/inbox` naming this file.

- `blocking: no`: carry on with your recommendation, marked "assumed, owner can overrule".
- `blocking: yes`: pause only the parts the question touches.
- Nothing open: replace the questions with the single line `none open`, send no Q item, and start building.

Already answered (not re-asked): `<refs to earlier answers, or none>`

## 1. <the question, one sentence>
blocking: yes|no
- A: <option>
- B: <option>
- C: <option, if there is a third>
Recommended: <A|B|C>, because <one line of why>.
Touches: <the parts of the job this decides>

## 2. <next question>
blocking: yes|no
- A: <option>
- B: <option>
Recommended: <A|B>, because <one line of why>.
Touches: <...>

## Answers (filled in when they arrive)
| # | answer | from (owner's words, or "coordinator ruling") | UTC |
|---|---|---|---|
