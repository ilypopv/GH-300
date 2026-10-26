"""Local mock-exam site: serves the question bank parsed from mock-exams/*.md.

Run with ``mock-exam`` (or ``mock-exams``) once the venv is active, or ``uv run mock-exam``. Questions are parsed once at startup. Progress
(answers and finished tests) is persisted to ``progress.json`` in the repo root.
"""

import json
import re
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

import markdown
from flask import Flask, jsonify, request, send_from_directory

ROOT = Path(__file__).parent
MOCK = ROOT / "mock-exams"
PROGRESS = ROOT / "progress.json"
PORT = 8765

app = Flask(__name__, static_folder=str(ROOT / "static"), static_url_path="/static")

TAG_RE = re.compile(r"^`([^`]+)`(?: · `select (\d+)`)?\s*$", re.MULTILINE)
OPT_RE = re.compile(r"^- \[( |x)\] (.*)$", re.MULTILINE)


def parse_file(path):
    """Parses one converted mock-exam Markdown file into question dicts.

    Args:
        path: Path to a ``NN.md`` file in the converted format (``## N.``
            headings, a domain tag line, checkbox options, a ``<details>``
            explanation block).

    Returns:
        A list of dicts with the keys ``id``, ``exam``, ``num``, ``domain``,
        ``stem`` (list of paragraphs), ``options`` (list of ``{"text",
        "correct"}``), ``need`` (number of correct options) and
        ``explanation`` (HTML).
    """
    text = path.read_text(encoding="utf-8")
    exam = int(path.stem)
    parts = re.split(r"\n## (\d+)\. ", text)
    out = []
    for i in range(1, len(parts), 2):
        num = int(parts[i])
        body = parts[i + 1]
        tag = TAG_RE.search(body)
        details = body.find("<details>")
        stem = [p.strip() for p in re.split(r"\n\s*\n", body[: tag.start()].strip()) if p.strip()]
        opts = [{"text": t.strip(), "correct": c == "x"} for c, t in OPT_RE.findall(body[tag.end() : details])]
        exp_md = body[details:].split("<summary>Explanation</summary>", 1)[1].split("</details>")[0]
        exp_html = markdown.markdown(exp_md.strip()).replace("<a href", '<a target="_blank" rel="noopener" href')
        out.append(
            {
                "id": f"{exam}-{num}",
                "exam": exam,
                "num": num,
                "domain": tag.group(1),
                "stem": stem,
                "options": opts,
                "need": sum(o["correct"] for o in opts),
                "explanation": exp_html,
            }
        )
    return out


def load_all():
    """Loads every question from all ``mock-exams/NN.md`` files.

    Returns:
        A flat list of question dicts, ordered by exam file and question number.
    """
    qs = []
    for f in sorted(MOCK.glob("[0-9][0-9].md")):
        qs += parse_file(f)
    return qs


QUESTIONS = load_all()


@app.route("/")
def index():
    """Serves the single-page UI.

    Returns:
        The ``static/index.html`` response.
    """
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/questions")
def questions():
    """Returns the whole question bank, including correct answers.

    Returns:
        A JSON list of question dicts (see ``parse_file``).
    """
    return jsonify(QUESTIONS)


def read_progress():
    """Reads saved progress from disk.

    Returns:
        The progress dict with ``questions`` (per-question attempt stats keyed
        by question id) and ``sessions`` (finished tests). An empty structure
        is returned if the file is missing or unreadable.
    """
    if PROGRESS.exists():
        try:
            return json.loads(PROGRESS.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {"questions": {}, "sessions": []}


def write_progress(data):
    """Writes progress to disk atomically via a temp file and rename.

    Args:
        data: The progress dict to persist.
    """
    tmp = PROGRESS.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(PROGRESS)


@app.route("/api/progress")
def get_progress():
    """Returns the saved progress.

    Returns:
        A JSON progress dict (see ``read_progress``).
    """
    return jsonify(read_progress())


@app.route("/api/answer", methods=["POST"])
def post_answer():
    """Records one checked answer.

    Expects a JSON body with ``id`` (question id) and ``ok`` (whether the
    answer was correct).

    Returns:
        The updated stats record for that question.
    """
    b = request.get_json()
    data = read_progress()
    r = data["questions"].setdefault(b["id"], {"attempts": 0, "correct": 0})
    r["attempts"] += 1
    r["correct"] += 1 if b["ok"] else 0
    r["last_ok"] = bool(b["ok"])
    r["last_ts"] = datetime.now().isoformat(timespec="seconds")
    write_progress(data)
    return jsonify(r)


@app.route("/api/session", methods=["POST"])
def post_session():
    """Appends a finished test summary to the session history.

    Expects a JSON body with the session summary (``total``, ``answered``,
    ``correct``, ``ms``); a server-side timestamp is added.

    Returns:
        A JSON ``{"ok": true}`` acknowledgement.
    """
    data = read_progress()
    data["sessions"].append({**request.get_json(), "ts": datetime.now().isoformat(timespec="seconds")})
    write_progress(data)
    return jsonify(ok=True)


@app.route("/api/reset", methods=["POST"])
def reset():
    """Erases all saved progress.

    Returns:
        A JSON ``{"ok": true}`` acknowledgement.
    """
    write_progress({"questions": {}, "sessions": []})
    return jsonify(ok=True)


def main():
    """Starts the server and opens the site in the default browser."""
    print(f"{len(QUESTIONS)} questions loaded -> http://127.0.0.1:{PORT}")
    threading.Timer(1, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    app.run(host="127.0.0.1", port=PORT)


if __name__ == "__main__":
    main()
