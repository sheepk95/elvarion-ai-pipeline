"""Exercise inbox delivery and job pins in a new temp folder. Records are fixtures, not agent approvals."""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "pipeline/tools"


def run(script, *args, expected=0):
    result = subprocess.run([sys.executable, "-I", "-B", str(TOOLS / script), *map(str, args)],
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    if result.returncode != expected:
        raise RuntimeError("%s: expected exit %d, got %d\n%s\n%s" %
                           (script, expected, result.returncode, result.stdout, result.stderr))
    return result.stdout


def main():
    workspace = Path(tempfile.mkdtemp(prefix="elvarion demo "))
    print("Fixture workspace (retained):", workspace, flush=True)
    job = workspace / "jobs/demo-1"
    inbox = workspace / "lanes/demo/inbox/reviewer"
    job.mkdir(parents=True)
    inbox.mkdir(parents=True)
    (workspace / "SCORE-CARD.md").write_text("# Demo criteria\nThe deliverable says hello.\n", encoding="utf-8")
    deliverable = workspace / "hello.txt"
    deliverable.write_text("hello\n", encoding="utf-8")
    (job / "JOB.md").write_text(
        "# JOB demo-1 (LOCAL FIXTURE ONLY)\nSystems: demo\nWork: file | hello.txt\n"
        "Attempt log: none, because this is a local tool fixture\n"
        "Scorecard: `SCORE-CARD.md` v1\nReads: none\n", encoding="utf-8")
    output = run("job_pins.py", "demo-1", "--root", workspace)
    pin = next(line for line in output.splitlines() if line.startswith("pins: "))
    print(run("send_item.py", "--to", inbox, "--from", "demo-builder", "--kind", "REVIEW-ASK",
              "--body", "LOCAL FIXTURE ONLY\n" + pin).strip())
    item = next(inbox.glob("*.md"))
    received = run("wait_inbox.py", inbox, "--timeout", "5")
    if str(item) not in received:
        raise RuntimeError("waiter did not return the submitted item")
    print("Received:", item.name)
    (inbox / ".seen").write_text(item.name + "\n", encoding="utf-8")
    for kind in ("REVIEW", "TEST", "GATE"):
        (job / (kind + "-1.md")).write_text("# LOCAL FIXTURE ONLY: " + kind + "\n" + pin +
                                            "\nNo agent review or owner approval is claimed.\n", encoding="utf-8")
    print(run("job_pins.py", "demo-1", "--root", workspace, "--check").splitlines()[0])
    deliverable.write_text("changed after the fixture records were written\n", encoding="utf-8")
    rejected = run("job_pins.py", "demo-1", "--root", workspace, "--check", expected=1)
    if "MISMATCH" not in rejected:
        raise RuntimeError("changed work failed without the expected mismatch diagnostic")
    print("Changed deliverable correctly rejected.")
    print("DEMO PASS (file protocol and identity only; no AI or human approvals)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
