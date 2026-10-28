#!/usr/bin/env python3
"""
Helios Write-Through Guard Hook for Antigravity (PreInvocation).

Inspects the recent conversation trajectory. If the agent performed workspace
or infrastructure mutations (file writes, edits, docker, git commits) without
invoking `helios.save_memory` via MCP, injects an ephemeral cognitive reminder
to enforce the Write-Through Definition of Done before finishing the turn.
"""

import json
import os
import re
import sys

MUTATING_TOOLS = {"edit_file", "write_file"}
MUTATING_COMMAND_PATTERNS = [
    r"\bdocker\s+(compose\s+)?(up|run|restart|build|stop|rm)\b",
    r"\bgit\s+(commit|push|rebase|merge|tag)\b",
    r"\bgh\s+(repo|release|pr\s+create|workflow)\b",
    r"\bsystemctl\s+(start|stop|restart|enable)\b",
]
CLIENT_CONFIG_IGNORE_PATTERNS = [
    r"(^|[\\/])\.(gemini|cursor|claude|codex|codeium|windsurf|opencode|vscode|agents)([\\/]|$)",
    r"(^|[\\/])(GEMINI|CLAUDE|AGENTS)\.md$",
    r"(^|[\\/])global_rules\.md$",
    r"(^|[\\/])copilot-instructions\.md$",
    r"(^|[\\/])(mcp|mcp_config|claude_desktop_config|opencode|hooks)\.jsonc?$",
    r"(^|[\\/])config\.toml$",
    r"(^|[\\/])helios_guard\.py$",
    r"(^|[\\/])SKILL\.md$",
]


def is_ignored_client_path(path: str, artifact_dir: str = "") -> bool:
    """Return True if path is inside artifact_dir or is a local AI client config/directive file."""
    if not path:
        return False
    if artifact_dir and path.startswith(artifact_dir):
        return True
    return any(re.search(pat, path, flags=re.IGNORECASE) for pat in CLIENT_CONFIG_IGNORE_PATTERNS)


def check_recent_trajectory(transcript_path: str, artifact_dir: str = "") -> bool:
    """Return True if recent steps contained unpersisted mutations."""
    if not transcript_path or not os.path.isfile(transcript_path):
        return False

    try:
        # Read the last ~40KB of the transcript
        file_size = os.path.getsize(transcript_path)
        read_bytes = min(file_size, 40960)
        with open(transcript_path, "rb") as f:
            if file_size > read_bytes:
                f.seek(file_size - read_bytes)
            chunk = f.read().decode("utf-8", errors="ignore")

        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not lines:
            return False

        has_mutation = False
        has_memory_capture = False

        # Scan backwards from the newest steps (up to 20 steps)
        for raw_line in reversed(lines[-20:]):
            try:
                step = json.loads(raw_line)
            except Exception:
                continue

            tool_calls = step.get("tool_calls", [])
            for tc in tool_calls:
                name = tc.get("name", "")
                args = tc.get("args", {})

                # Check if helios memory was saved
                if name == "call_mcp_tool" and args.get("ServerName") == "helios":
                    tool_name = args.get("ToolName", "")
                    if tool_name in ("save_memory", "deprecate_memory", "revalidate_memories"):
                        has_memory_capture = True
                elif "helios_save_memory" in name:
                    has_memory_capture = True

                # Check if a file was mutated outside the artifact/client-config directories
                if name in MUTATING_TOOLS:
                    target_path = str(args.get("Path", ""))
                    if not is_ignored_client_path(target_path, artifact_dir):
                        has_mutation = True

                # Check if mutating shell command was executed
                if name == "run_command":
                    cmd = str(args.get("CommandLine", ""))
                    for pat in MUTATING_COMMAND_PATTERNS:
                        if re.search(pat, cmd, flags=re.IGNORECASE):
                            has_mutation = True
                            break

        return has_mutation and not has_memory_capture
    except Exception:
        return False


def main():
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            print(json.dumps({"injectSteps": []}))
            return

        payload = json.loads(raw_input)
        transcript_path = payload.get("transcriptPath", "")
        artifact_dir = payload.get("artifactDirectoryPath", "")

        needs_nudge = check_recent_trajectory(transcript_path, artifact_dir)
        if needs_nudge:
            message = (
                "⚠️ HELIOS WRITE-THROUGH GUARD: You have executed workspace or infrastructure modifications. "
                "Remember: tasks are INCOMPLETE until persistent architectural changes, ports, or non-obvious fixes "
                "are recorded in Helios via helios.save_memory. Do not conclude your turn without persisting state."
            )
            output = {"injectSteps": [{"ephemeralMessage": message}]}
        else:
            output = {"injectSteps": []}

        print(json.dumps(output))
    except Exception:
        # Fallback cleanly so the agent loop is never interrupted
        print(json.dumps({"injectSteps": []}))


if __name__ == "__main__":
    main()
