# Experimental release preparation

These are proposed owner actions after reviewing and integrating the fixes. This document does not change repository
settings, create a tag or release, enable a service, or make the repository public.

Suggested description:

> Experimental Windows toolkit for file-coordinated AI development: job pins, inboxes, review gates and GPU leases.

Suggested topics: `ai-agents`, `agent-workflow`, `python`, `windows`, `game-development`, `claude-code`.

Suggested first tagged release: `v0.1.1`, titled **Experimental Windows starter kit — reliability fixes**.
Use the actual accepted commit when creating the tag; do not tag the original reviewed snapshot by mistake.

Proposed release notes:

- Strengthen job evidence identity, concurrent inbox delivery and GPU coordination.
- Reject visual reviews without the required image evidence.
- Distinguish installed skills from reviewed skills; improve clean-directory and spaced-path setup.
- Add Windows checks, a local walkthrough and contributor guidance.
- Experimental scope: the CPU checks do not certify live desktop wake-ups, real GPU admission or animation quality.

Before release, run the exact accepted tree through CI, check the public diff for private data and third-party
files, and perform the live-host/hardware acceptance checks relevant to the claims in the release. If those checks
remain pending, say so in the release notes. Keep the repository private until the owner explicitly approves a
visibility change. Optional branch protection and private vulnerability reporting should be configured by the owner
after the new CI check has run successfully.
