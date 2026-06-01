#!/usr/bin/env python3
from flask import Flask, request, jsonify, send_from_directory, send_file
from pathlib import Path
from dotenv import load_dotenv
import anthropic, json, os, re

load_dotenv(dotenv_path=Path(__file__).parent / ".env", encoding="utf-8-sig")

BASE = Path(__file__).parent
POSTS_FILE        = BASE / "posts.json"
AGENT_OUTPUT_FILE = BASE / "agent_output.json"
DRAFTS_FILE       = BASE / "drafts.json"

app = Flask(__name__, static_folder=str(BASE), static_url_path="")

def parse_json(text):
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    text = text.strip()
    start = min((text.find(c) for c in ['{','['] if text.find(c) != -1), default=0)
    end   = max((text.rfind(c) for c in ['}',']'] if text.rfind(c) != -1), default=len(text))
    return json.loads(text[start:end+1])

@app.route("/")
def index():
    return send_from_directory(BASE, "studio.html")

@app.route("/visual-builder")
def visual_builder():
    return send_from_directory(BASE, "visual_builder.html")

@app.route("/api/posts", methods=["GET"])
def get_posts():
    try:
        return POSTS_FILE.read_text(encoding="utf-8"), 200, {"Content-Type": "application/json"}
    except FileNotFoundError:
        return "[]", 200, {"Content-Type": "application/json"}

@app.route("/api/posts", methods=["POST"])
def save_posts():
    POSTS_FILE.write_text(json.dumps(request.get_json(), indent=2, ensure_ascii=False), encoding="utf-8")
    return jsonify({"ok": True})

@app.route("/api/agent-output", methods=["GET"])
def agent_output():
    try:
        return AGENT_OUTPUT_FILE.read_text(encoding="utf-8"), 200, {"Content-Type": "application/json"}
    except FileNotFoundError:
        return jsonify({"recommendation": None, "overdue": [], "context_was_updated": False})

@app.route("/api/drafts", methods=["GET"])
def get_drafts():
    try:
        return DRAFTS_FILE.read_text(encoding="utf-8"), 200, {"Content-Type": "application/json"}
    except FileNotFoundError:
        return "{}", 200, {"Content-Type": "application/json"}

@app.route("/api/generate-draft", methods=["POST"])
def generate_draft():
    print("generate-draft called")
    try:
        data = request.get_json()
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        print(f"API key present: {bool(api_key)}")
        if not api_key:
            return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 500

        client = anthropic.Anthropic(api_key=api_key)
        post_info = (
            f"Topic: {data.get('topic','')}\n"
            f"Hook: {data.get('hook','')}\n"
            f"Category: {data.get('category','')}\n"
            f"Notes: {data.get('notes','')}"
        )
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role":"user","content":(
                "You are writing a LinkedIn post for Ana Jiménez, a hospitality professional "
                "transitioning into tech. She documents her real journey building JobMatch AI.\n\n"
                "Voice rules:\n"
                "- First person, conversational\n"
                "- No em dashes\n"
                "- No bullet points or numbered lists\n"
                "- Short paragraphs of 1-3 sentences\n"
                "- Ends with a quiet reflective closer, not a call to action\n"
                "- Grounded in specific real details\n\n"
                f"Post to draft:\n{post_info}\n\n"
                "Return ONLY valid JSON, no markdown fences:\n"
                "{\"text\": \"...\", \"hashtags\": [...], \"visual_prompt\": \"...\"}"
            )}]
        )
        result = parse_json(response.content[0].text)
        draft = {
            "text":          result.get("text", ""),
            "hashtags":      result.get("hashtags", []),
            "visual_prompt": result.get("visual_prompt", ""),
        }

        # Persist to drafts.json keyed by post ID
        post_id = str(data.get("id", "")).strip()
        print(f"post_id from request: '{post_id}'")
        if post_id:
            all_drafts = {}
            if DRAFTS_FILE.exists():
                try:
                    all_drafts = json.loads(DRAFTS_FILE.read_text(encoding="utf-8"))
                except Exception:
                    all_drafts = {}
            all_drafts[post_id] = draft
            DRAFTS_FILE.write_text(
                json.dumps(all_drafts, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            print(f"Draft saved → {DRAFTS_FILE} (keys: {list(all_drafts.keys())})")
        else:
            print("WARNING: no post_id in request — draft not persisted")

        return jsonify({**draft, "cached": False})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print(f"Content Studio → http://localhost:5001")
    app.run(host="localhost", port=5001, debug=False)