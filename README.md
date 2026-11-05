# Elvarion AI pipeline

I'm a solo indie dev and AI developer making **Elvarion**, an RTS game in Unity. I don't have a studio, so I
built one out of AI agents: a set of Claude Code chats (plus a few Codex helpers) that plan, build, review, test
and integrate the game's work, coordinated through plain files on one Windows PC.

This repo is the pipeline I have running so far: **the process and the tools, not the game.** The game's code
and art stay private. Borrow the parts that fit your own project.

## How it works, in one picture

```
You (one desk chat you talk to)
 |
 v
Coordinator chat ---- writes job cards with acceptance criteria, paces the lanes
 |
 v
N lanes, each with:
  - one continuing builder   (medium reasoning)
  - one continuing reviewer  (high reasoning, one step above the builder)
  - one fresh gate reviewer per finished job (extra-high reasoning)
 |
 v
Integrator (merges) -> player testing with real input
```

- **One desk.** You talk to one chat. Every other chat sends its questions and loop updates there as files, so you
  never hunt through a dozen chats for the one that is waiting on you. ([docs/desk.md](docs/desk.md))
- **Lanes talk by inbox files.** Work items travel as inbox files; the only direct messages are short wake-ups and the one copy of a
  question sent to the desk chat. `send_item.py` drops a small Markdown item into the receiver's inbox folder; a
  background `wait_inbox.py` wakes the receiver when it lands.
  ([pipeline/](pipeline/))
- **Job cards first.** No build starts without written acceptance criteria, and the card pins what was built,
  tested and gated, so what merges is what passed.
- **The review ladder.** Each reviewer runs one reasoning step above the work it checks and writes its findings as
  fix recipes. A fresh gate reviewer that never saw the builder's reasoning decides pass or fail.
  ([docs/review-ladder.md](docs/review-ladder.md), [docs/picking-agents.md](docs/picking-agents.md))
- **Book the GPU.** Agents book the GPU before any GPU job (game engine, Blender, local models) so parallel chats
  never overload the machine. ([gpu-lease/](gpu-lease/))
- **Skills, picked per task.** Small skill files, and a librarian chat that tells each new chat which ones fit its
  task, so no agent has to read hundreds of them. ([librarian/](librarian/), [skills/](skills/))
- **Shared memory.** Decisions and lessons go into a memory server that every chat reads at start. I use
  [GBrain](https://github.com/garrytan/gbrain) for that; it is not part of this repo. [hooks/](hooks/) has the hook
  that hands each new chat and subagent its memory recipe.
- **Animation from video.** An AI-generated video take becomes a 3D body per frame with SAM 3D Body, then gets
  remapped onto a game rig in Blender and has to pass a review gate. ([docs/animation.md](docs/animation.md),
  [animation/](animation/))

Start with [docs/overview.md](docs/overview.md).

## What's in this repo

| Folder | What it is |
|---|---|
| [docs/](docs/) | How the setup fits together: overview, desk, review ladder, picking agents, animation |
| [pipeline/](pipeline/) | The lane pipeline: the brief, short rules, coordinator / job card / gate templates, an example lane, a worked example, and the inbox tools |
| [desk/](desk/) | Tools for the one chat you talk to: read new desk lines, wait for a new question, wake at a time |
| [gpu-lease/](gpu-lease/) | A small ledger that agents use to book and release the GPU |
| [librarian/](librarian/) | The skill librarian: a file mailbox between chats and a long-lived librarian chat, plus the skill index builder |
| [hooks/](hooks/) | A Claude Code hook that injects a recipe into every new chat and subagent |
| [skills/](skills/) | Six verification skills (tests that can fail, measuring the right thing, shared trees) |
| [animation/](animation/) | Scripts from the video-to-animation remap kit |

## What's not in this repo

- The game: its source, art, models, animations and any bought assets.
- My memory database, chat transcripts, decision logs and live pipeline state.
- Third-party code and skills. They are linked in [THIRD-PARTY.md](THIRD-PARTY.md) under their own licences.
- Any keys, tokens or account details.

## Requirements

- Windows 10/11. Some tools use Windows APIs; most are Python 3.11+ standard library only.
- Claude Code (desktop app or CLI). Codex is optional.
- Paths in the docs are written as `<USER_HOME>` (your home folder) and `<PROJECT_ROOT>` (the folder that holds
  your project and its agent workspace). The tools read their folders from environment variables or work them out
  from their own location; each script says which at the top.
- The animation scripts also need SAM 3D Body (fetched yourself from Meta), Blender, and for the rig examples the
  paid Auto-Rig Pro add-on.

## Status

This is a working setup, not a polished product. It grew one rule at a time while I was making a game, and it
still does. If people find it useful I'll keep cleaning it up and add more of the tools. Feedback is welcome in
Issues.

## Licence

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
