"""Run the Windows CPU-only checks; retain complete logs and a machine-readable summary."""
import argparse
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SUITES = {
    "pins": ["pipeline/tools/job_pins.py", "--self-test"],
    "reads": ["pipeline/tools/test_job_pins_reads.py"],
    "pin-integrity": ["pipeline/tools/test_job_pins_integrity.py"],
    "inbox": ["pipeline/tools/test_send_item.py"],
    "census": ["pipeline/tools/test_switch_census.py"],
    "hooks": ["hooks/test_inject_recipe.py"],
    "desk": ["desk/tools/test_desk_tools.py"],
    "desk-exits": ["desk/tools/test_desk_watch_exits.py"],
    "desk-pipeline": ["desk/tools/test_desk_watch_pipeline.py"],
    "desk-robust": ["desk/tools/test_desk_robustness.py"],
    "gpu-safety": ["gpu-lease/scripts/test_gpu_safety.py"],
    "visual-review": ["animation/sam3dbody-remap/test_check_review.py"],
    "checkpoint": ["animation/sam3dbody-remap/test_verify_checkpoint.py"],
    "librarian": ["librarian/test_build_index.py"],
    "librarian-inbox": ["librarian/test_librarian_inbox.py"],
    "demo": ["tools/demo_job.py"],
}


def parse_sources():
    count = 0
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in {".git", ".venv", "venv", "__pycache__", ".check-logs"}
                   and Path(folder, d) != ROOT / "animation/sam3dbody-remap/src"]
        for name in files:
            if name.endswith(".py"):
                path = Path(folder, name)
                ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
                count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=SUITES, action="append", help="run only these suites (repeatable)")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("the complete suite targets Windows; individual portable tests may be run separately")
    logs = Path(tempfile.mkdtemp(prefix="elvarion-checks-"))
    print("Logs:", logs, flush=True)
    results = []
    try:
        count = parse_sources()
        results.append({"name": "syntax", "exit_code": 0, "files": count})
        print("PASS syntax (%d Python files)" % count, flush=True)
    except (SyntaxError, OSError, UnicodeError) as exc:
        results.append({"name": "syntax", "exit_code": 1, "error": str(exc)})
        print("FAIL syntax:", exc, flush=True)
    for name in args.only or SUITES:
        log = logs / (name + ".log")
        command = [sys.executable, "-I", "-B", *SUITES[name]]
        started = time.monotonic()
        error = None
        try:
            with log.open("w", encoding="utf-8") as stream:
                completed = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=600)
            code = completed.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            code, error = 1, str(exc)
        results.append({"name": name, "exit_code": code, "command": command, "log": str(log),
                        "seconds": round(time.monotonic() - started, 2), "error": error})
        print("%s %s (exit %s)" % ("PASS" if code == 0 else "FAIL", name, code), flush=True)
        if code:
            if error:
                print(error, flush=True)
            if log.exists():
                print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]), flush=True)
    failed = [r["name"] for r in results if r["exit_code"] != 0]
    summary = {"python": sys.version, "root": str(ROOT), "results": results, "failed": failed}
    (logs / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("RESULT %s; summary: %s" % ("FAIL" if failed else "PASS", logs / "summary.json"), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
