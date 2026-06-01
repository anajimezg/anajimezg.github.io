#!/usr/bin/env python3
"""
update_context.py — Manual context updater for jobmatch_context.json

Run this after a Claude Code session to tell the agent what you just built
or decided. Claude parses the description, decides which field it belongs in,
formats the entry, and appends it.

Usage:
  python update_context.py "Added ATS score panel — shows keyword match percentage
                             and missing skills side by side"

Fields Claude can update:
  in_progress, learnings, recent_decisions, phases, update_log
"""

import json
import os
import sys
from datetime import datetime, timezone

from pathlib import Path
from dotenv import load_dotenv
import anthropic

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv(dotenv_path=Path(__file__).parent / ".env", encoding="utf-8-sig")

MODEL        = "claude-opus-4-8"
CONTEXT_FILE = "jobmatch_context.json"

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def parse_json_response(text: str) -> dict:
    """Strip optional markdown fences and parse as JSON."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        text = text.rsplit("```", 1)[0].strip()
    return json.loads(text)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Usage: python update_context.py "
            '"<description of what you built or decided>"'
        )
        sys.exit(1)

    description = sys.argv[1]

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY not set. Add it to your .env file.")
        sys.exit(1)

    client  = anthropic.Anthropic()
    context = load_json(CONTEXT_FILE)

    print(f'Parsing: "{description}"')

    # Ask Claude to decide where this description belongs and how to format it.
    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": (
                    "You are a context manager for a developer's project log.\n"
                    "The developer has just described something they built or decided. "
                    "Your job is to:\n"
                    "1. Decide which field in the context JSON this belongs in "
                    "(in_progress, learnings, recent_decisions, phases, or update_log).\n"
                    "2. Format the entry correctly for that field.\n"
                    "3. Return a JSON object with two fields:\n"
                    "   - field: the name of the field to append to (string)\n"
                    "   - entry: the value to append (string, or an object if "
                    "appending to phases)\n\n"
                    "Never modify or remove existing entries — only append.\n\n"
                    f"Current context:\n{json.dumps(context, indent=2)}\n\n"
                    f'Developer\'s description: "{description}"\n\n'
                    "Return only valid JSON, no markdown fences."
                ),
            }
        ],
    )

    result = parse_json_response(response.content[0].text)
    field  = result["field"]
    entry  = result["entry"]

    # Append the entry to the chosen field.
    if field == "update_log":
        # The description itself is the log entry.
        context["update_log"].append({
            "timestamp": utc_now(),
            "source":    "update_context.py manual",
            "note":      description,
        })
    elif field in context and isinstance(context[field], list):
        if entry not in context[field]:
            context[field].append(entry)
        # Always record what was added, even for list fields.
        context["update_log"].append({
            "timestamp":  utc_now(),
            "source":     "update_context.py manual",
            "description": description,
            "added_to":   field,
        })
    elif field in context and isinstance(context[field], dict):
        # For dict fields like `phases`, entry should be a dict of new key/value pairs.
        if isinstance(entry, dict):
            context[field].update(entry)
        else:
            print(f"Warning: field '{field}' is a dict but Claude returned a non-dict entry. Skipping.")
            sys.exit(1)
        context["update_log"].append({
            "timestamp":  utc_now(),
            "source":     "update_context.py manual",
            "description": description,
            "added_to":   field,
        })
    else:
        # Fallback: set the field directly.
        context[field] = entry
        context["update_log"].append({
            "timestamp":  utc_now(),
            "source":     "update_context.py manual",
            "description": description,
            "added_to":   field,
        })

    save_json(CONTEXT_FILE, context)
    print(f"Added to '{field}': {entry}")
    print("update_log entry appended.")


if __name__ == "__main__":
    main()
