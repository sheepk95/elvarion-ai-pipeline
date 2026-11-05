# Third-party projects

Nothing below is bundled in this repo. These are the projects the pipeline uses or that the scripts expect you to
install yourself, each under its own licence and terms.

| Project | Used for | Licence or terms |
|---|---|---|
| [Claude Code](https://claude.com/claude-code) | Every chat, subagent and hook in the pipeline | Anthropic's terms |
| [Codex](https://github.com/openai/codex) (optional) | A few helper and reviewer jobs | Apache-2.0 (the CLI); OpenAI's terms for the service |
| [GBrain](https://github.com/garrytan/gbrain) | The shared memory server the chats read and write | MIT |
| [SAM 3D Body](https://github.com/facebookresearch/sam-3d-body) and its [weights](https://huggingface.co/facebook/sam-3d-body-vith) (gated) | A 3D body per video frame (animation scripts); you fetch both yourself | Meta's SAM License: commercial use allowed, some end uses barred; read it before you use the model |
| PyTorch, NumPy, OpenCV, roma, ffmpeg, the Hugging Face `hf` command | Packages and tools the animation scripts use | Each under its own licence |
| [Blender](https://www.blender.org/) | Remapping, renders and FBX export (animation scripts) | GPL |
| Auto-Rig Pro | The rig the remap examples target | Paid Blender add-on |
| [Unity](https://unity.com/) | The game engine the pipeline builds for | Unity's terms |
| MiniMax | The AI video takes the animation process starts from | Paid service, its own terms |
| [gitleaks](https://github.com/gitleaks/gitleaks) | Scanning this repo for leaked secrets before release | MIT |

Scripts that import `bpy` run inside Blender (GPL-3.0-or-later). This repo ships them under Apache-2.0, which is
GPLv3-compatible; a Blender add-on built and redistributed from them is GPL.

The pipeline also uses skills written by other people, from public skill collections. None of them is copied here:
the six skills in [skills/](skills/) are my own.
