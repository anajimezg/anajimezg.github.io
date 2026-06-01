#!/usr/bin/env python3
"""
JobMatch AI Agent
-----------------
Two-part agent that runs on demand:

  Part 1 — Context Updater
    Asks Claude to review jobmatch_context.json and suggest any updates.
    If updates are needed, merges them in and appends a timestamp to update_log.

  Part 2 — Recommendation Generator
    Asks Claude to recommend the next LinkedIn post to write, informed by
    both the content pipeline (posts.json) and what's been built in JobMatch.

Usage:
  python agent.py

Output:
  Prints a summary to the terminal and writes agent_output.json.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

from pathlib import Path
from dotenv import load_dotenv
import anthropic

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv(dotenv_path=Path(__file__).parent / ".env", encoding="utf-8-sig")

# Use the latest, most capable Claude model.
# Switch to "claude-haiku-4-5" here for cheaper / faster runs during testing.
MODEL = "claude-opus-4-8"

CONTEXT_FILE = "jobmatch_context.json"
POSTS_FILE   = "posts.json"
OUTPUT_FILE  = "agent_output.json"

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_json(path: str) -> dict | list:
    """Read and parse a JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: dict | list) -> None:
    """Write data to a JSON file with pretty-printing."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def parse_json_response(text):
    """Strip markdown code fences and parse JSON robustly."""
    import re
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    text = text.strip()
    # Find the first { or [ and last } or ] to extract just the JSON
    start = min(
        (text.find(c) for c in ['{', '['] if text.find(c) != -1),
        default=0
    )
    end = max(
        (text.rfind(c) for c in ['}', ']'] if text.rfind(c) != -1),
        default=len(text)
    )
    return json.loads(text[start:end+1])


def utc_now() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ── Part 1: Context Updater ───────────────────────────────────────────────────

def update_context(client: anthropic.Anthropic, context: dict) -> tuple[dict, bool]:
    """
    Ask Claude to review the project context and suggest updates.

    Returns the (possibly updated) context dict and a boolean indicating
    whether any changes were made.
    """
    print("Part 1: Reviewing project context for updates...")

    # The instruction given to Claude — kept as a literal string so it's easy to tweak.
    instruction = (
        "You are a context updater for a developer's project log. "
        "Review the existing context and identify if anything looks outdated or incomplete "
        "based on general knowledge of how Flask/Python job search apps evolve. "
        "Return a JSON object with two fields: "
        "should_update (boolean) and updates (an object with any fields from the context "
        "that should be appended or modified). "
        "Only suggest updates if genuinely needed. "
        "Never remove existing entries — only append. "
        "Return only valid JSON, no markdown fences."
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": (
                    f"{instruction}\n\n"
                    f"Current context:\n{json.dumps(context, indent=2)}"
                ),
            }
        ],
    )

    result = parse_json_response(response.content[0].text)

    if not result.get("should_update"):
        print("  → Context looks up to date. No changes needed.")
        return context, False

    # Merge the suggested updates into the existing context.
    updates = result.get("updates", {})
    for field, value in updates.items():
        if isinstance(value, list) and isinstance(context.get(field), list):
            # Append new list items, skipping duplicates.
            existing = context[field]
            for item in value:
                if item not in existing:
                    existing.append(item)
        elif isinstance(value, dict) and isinstance(context.get(field), dict):
            context[field].update(value)
        else:
            context[field] = value

    # Record this automated update in the log.
    context["update_log"].append({
        "timestamp": utc_now(),
        "source": "agent.py auto-update",
        "changes": list(updates.keys()),
    })

    save_json(CONTEXT_FILE, context)
    print(f"  → Context updated. Fields changed: {list(updates.keys())}")
    return context, True


# ── Part 2: Recommendation Generator ─────────────────────────────────────────

def generate_recommendation(
    client: anthropic.Anthropic,
    context: dict,
    posts: list,
) -> tuple[str, list]:
    """
    Ask Claude to recommend the next LinkedIn post, then identify overdue posts.

    Returns:
      recommendation — 2-3 sentence string addressed to Ana.
      overdue        — list of post IDs where the date has passed and status != Published.
    """
    print("Part 2: Generating post recommendation...")

    # Find overdue posts: scheduled date in the past, not yet published.
    # ISO date strings sort lexicographically, so string comparison works correctly.
    today = datetime.now(timezone.utc).date().isoformat()
    overdue = [
        p["id"]
        for p in posts
        if p.get("date") and p["date"] < today and p.get("status") != "Published"
    ]

    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": (
                    "You are a content strategist advising Ana, a hospitality professional "
                    "transitioning into tech. She writes LinkedIn posts about her journey "
                    "building JobMatch AI — a real tool she created to solve her own job "
                    "search problems.\n\n"
                    f"Her current content pipeline (posts.json):\n"
                    f"{json.dumps(posts, indent=2)}\n\n"
                    f"The latest context about what she has actually built (jobmatch_context.json):\n"
                    f"{json.dumps(context, indent=2)}\n\n"
                    "Based on both sources, recommend which post she should write next and why. "
                    "Write 2-3 sentences, conversational, as if advising Ana directly.\n\n"
                    "Return only valid JSON with a single field: recommendation (string). "
                    "No markdown fences."
                ),
            }
        ],
    )

    result = parse_json_response(response.content[0].text)
    recommendation = result.get("recommendation", "")
    return recommendation, overdue


# ── Part 3: Draft Generator ───────────────────────────────────────────────────

def generate_draft(
    client: anthropic.Anthropic,
    context: dict,
    posts: list,
    recommendation: str,
) -> dict:
    """
    Ask Claude to write a full LinkedIn post draft in Ana's voice for the
    recommended post.

    Returns a dict with:
      text          — the full post draft (newlines preserved)
      hashtags      — list of 4-5 hashtag words (no # symbol)
      visual_prompt — one sentence describing an ideal visual for the post
    """
    print("Part 3: Writing LinkedIn post draft...")

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": (
                    "You are writing a LinkedIn post for Ana Jiménez, a hospitality "
                    "professional transitioning into tech. She documents her real journey "
                    "building JobMatch AI — a tool she created to solve her own job search "
                    "problems.\n\n"
                    "Voice rules (follow strictly):\n"
                    "- First person, conversational\n"
                    "- No em dashes\n"
                    "- No bullet points or numbered lists\n"
                    "- Short paragraphs of 1-3 sentences\n"
                    "- Ends with a quiet, reflective closer — not a question or call to action\n"
                    "- Grounded in specific real details from the context below, not generic\n\n"
                    f"Content pipeline (posts.json):\n{json.dumps(posts, indent=2)}\n\n"
                    f"Project context (jobmatch_context.json):\n{json.dumps(context, indent=2)}\n\n"
                    f"The recommended post to write:\n{recommendation}\n\n"
                    "Return only valid JSON with three fields:\n"
                    "  text: the full post draft (string, newlines as \\n)\n"
                    "  hashtags: array of 4-5 hashtag words relevant to the post and Ana's "
                    "career transition (no # symbol, just the words)\n"
                    "  visual_prompt: one sentence describing the best visual for this post "
                    "(e.g. 'Screenshot of the ATS score panel showing keyword breakdown')\n"
                    "No markdown fences."
                ),
            }
        ],
    )

    result = parse_json_response(response.content[0].text)
    return {
        "text":          result.get("text", ""),
        "hashtags":      result.get("hashtags", []),
        "visual_prompt": result.get("visual_prompt", ""),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    # Fail early with a clear message if the API key is missing.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY not set. Add it to your .env file.")
        sys.exit(1)

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from environment

    # Load source files.
    context = load_json(CONTEXT_FILE)
    posts   = load_json(POSTS_FILE)

    # Part 1: update context if Claude thinks it's stale.
    context, context_was_updated = update_context(client, context)

    # Part 2: generate recommendation using the freshest context.
    recommendation, overdue = generate_recommendation(client, context, posts)

    # Part 3: write a full LinkedIn draft for the recommended post.
    draft = generate_draft(client, context, posts, recommendation)

    # Write structured output for downstream use.
    output = {
        "recommendation":      recommendation,
        "overdue":             overdue,
        "context_was_updated": context_was_updated,
        "draft":               draft,
    }
    save_json(OUTPUT_FILE, output)

    # Print a readable terminal summary.
    print()
    print("─" * 60)
    print("RECOMMENDATION")
    print("─" * 60)
    print(recommendation)
    print()
    if overdue:
        print(f"OVERDUE POSTS (past scheduled date, not published): {overdue}")
    else:
        print("No overdue posts.")
    print()
    print("─" * 60)
    print("DRAFT")
    print("─" * 60)
    print(draft.get("text", ""))
    if draft.get("hashtags"):
        print()
        print(" ".join(f"#{h}" for h in draft["hashtags"]))
    print()
    print(f"Context updated this run: {context_was_updated}")
    print(f"Full output written to {OUTPUT_FILE}")
    print("─" * 60)


if __name__ == "__main__":
    main()
