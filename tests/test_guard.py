import json
import subprocess
import sys
from pathlib import Path

GUARD_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "helios_guard.py"


def test_guard_script_clean_input(tmp_path):
    empty_transcript = tmp_path / "transcript.jsonl"
    empty_transcript.write_text("")

    payload = json.dumps({"transcriptPath": str(empty_transcript), "artifactDirectoryPath": str(tmp_path)})
    proc = subprocess.run(
        [sys.executable, str(GUARD_SCRIPT)],
        input=payload,
        text=True,
        capture_output=True,
        check=True,
    )
    data = json.loads(proc.stdout)
    assert data == {"injectSteps": []}


def test_guard_script_detects_mutation_without_save(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    step = {
        "step_index": 1,
        "source": "MODEL",
        "type": "PLANNER_RESPONSE",
        "tool_calls": [
            {"name": "run_command", "args": {"CommandLine": "docker compose up -d"}}
        ],
    }
    transcript.write_text(json.dumps(step) + "\n")

    payload = json.dumps({"transcriptPath": str(transcript), "artifactDirectoryPath": str(tmp_path)})
    proc = subprocess.run(
        [sys.executable, str(GUARD_SCRIPT)],
        input=payload,
        text=True,
        capture_output=True,
        check=True,
    )
    data = json.loads(proc.stdout)
    assert len(data["injectSteps"]) == 1
    assert "HELIOS WRITE-THROUGH GUARD" in data["injectSteps"][0]["ephemeralMessage"]


def test_guard_script_suppressed_when_memory_saved(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    step1 = {
        "step_index": 1,
        "source": "MODEL",
        "type": "PLANNER_RESPONSE",
        "tool_calls": [
            {"name": "run_command", "args": {"CommandLine": "docker compose up -d"}}
        ],
    }
    step2 = {
        "step_index": 2,
        "source": "MODEL",
        "type": "PLANNER_RESPONSE",
        "tool_calls": [
            {"name": "call_mcp_tool", "args": {"ServerName": "helios", "ToolName": "save_memory"}}
        ],
    }
    transcript.write_text(json.dumps(step1) + "\n" + json.dumps(step2) + "\n")

    payload = json.dumps({"transcriptPath": str(transcript), "artifactDirectoryPath": str(tmp_path)})
    proc = subprocess.run(
        [sys.executable, str(GUARD_SCRIPT)],
        input=payload,
        text=True,
        capture_output=True,
        check=True,
    )
    data = json.loads(proc.stdout)
    assert data == {"injectSteps": []}
