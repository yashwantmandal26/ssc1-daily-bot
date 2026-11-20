#!/usr/bin/env python3
"""
Natural Non-Repeating Official Meta API Auto-Reply Bot (@ssc1.daily)
--------------------------------------------------------------------
Runs 2x daily (~2 hours after each post) or on manual workflow_dispatch.
- Zero repeated reply templates on the same Reel (shuffled pool per post)
- Natural mix of short, medium, and full explanatory replies
- Occasional subtle follow nudge (~1 in 3 comments)
- Strict "-" punctuation (zero em-dashes)
"""

import json
import os
import random
import re
import time
from pathlib import Path

import requests

ROOT_DIR = Path(__file__).resolve().parent
REEL_PYQS_PATH = ROOT_DIR / "reel_pyqs.json"
OWN_USERNAME = "ssc1.daily"

IG_API_BASE = (
    "https://graph.instagram.com/v21.0"
    if os.environ.get("IG_ACCESS_TOKEN", "").startswith("IG")
    else "https://graph.facebook.com/v21.0"
)

# Varied pools mixing short, medium, and detailed explanatory styles
RIGHT_TEMPLATES = [
    # Short
    "Yes, correct.",
    "Sahi hai.",
    "Right, {ans} hi hoga.",
    # Medium + occasional follow nudge
    "Correct! {ans} is right - follow @ssc1.daily for daily SSC PYQs.",
    "Bilkul sahi. Daily aise hi PYQs ke liye follow kar lena.",
    # Detailed explanatory (#1 style)
    "Spot on - {expl}",
    "Correct answer. {expl}",
    "Exactly right! {expl} Follow @ssc1.daily for daily practice.",
]

WRONG_TEMPLATES = [
    # Short
    "Nahi, {ans} hoga.",
    "Close, correct answer {ans} hai.",
    "Actually {ans} hai sahi.",
    # Medium + occasional follow nudge
    "Tricky question tha - correct answer {ans} hai. Daily SSC PYQs ke liye follow kar sakte ho.",
    "Close! {ans} hoga. Follow @ssc1.daily for more such exam traps.",
    # Detailed explanatory (#1 style)
    "Close! Correct answer is {ans} - {expl}",
    "Actually {ans} hoga. {expl}",
    "Good try - {ans} is correct. {expl}",
]

GENERAL_TEMPLATES = [
    "Thanks!",
    "Thank you, glad it helped.",
    "Thanks! Follow @ssc1.daily for daily SSC CGL PYQs.",
    "Appreciate it - {ans} is the right answer here.",
    "Thanks! Daily 2 new PYQ traps aate hain, follow kar sakte ho.",
]


def extract_option_letter(text: str) -> str | None:
    cleaned = text.strip().lower()
    m = re.search(
        r"(?:^|[\s(])(?:option\s+|ans(?:wer)?\s*[:=-]?\s*)?([abcd])(?:[\s).!?:,]|$)",
        cleaned,
    )
    return m.group(1) if m else None


def extract_correct_letter(correct_answer: str) -> str | None:
    m = re.search(r"\(([a-dA-D])\)", correct_answer)
    return m.group(1).lower() if m else None


class ReplyStylePool:
    """Ensures no reply template repeats on the same Reel."""

    def __init__(self) -> None:
        self.pools = {
            "right": random.sample(RIGHT_TEMPLATES, len(RIGHT_TEMPLATES)),
            "wrong": random.sample(WRONG_TEMPLATES, len(WRONG_TEMPLATES)),
            "general": random.sample(GENERAL_TEMPLATES, len(GENERAL_TEMPLATES)),
        }

    def pick(self, bucket: str, ans: str, expl: str) -> str:
        if not self.pools[bucket]:
            base = (
                RIGHT_TEMPLATES
                if bucket == "right"
                else WRONG_TEMPLATES
                if bucket == "wrong"
                else GENERAL_TEMPLATES
            )
            self.pools[bucket] = random.sample(base, len(base))
        tpl = self.pools[bucket].pop()
        return tpl.format(ans=ans, expl=expl).replace("—", "-")


def build_varied_reply(comment_text: str, quiz: dict, pool: ReplyStylePool) -> str:
    correct_ans = quiz.get("correct_answer", "").strip().replace("—", "-")
    explanation = quiz.get("explanation", "").strip().replace("—", "-")
    correct_letter = extract_correct_letter(correct_ans)
    guessed_letter = extract_option_letter(comment_text)

    if guessed_letter and correct_letter:
        bucket = "right" if guessed_letter == correct_letter else "wrong"
        return pool.pick(bucket, correct_ans, explanation)

    ans_core = re.sub(r"^\([a-dA-D]\)\s*", "", correct_ans).lower()
    if ans_core and ans_core in comment_text.lower():
        return pool.pick("right", correct_ans, explanation)

    return pool.pick("general", correct_ans, explanation)


def fetch_comments(media_id: str, token: str) -> list[dict]:
    resp = requests.get(
        f"{IG_API_BASE}/{media_id}/comments",
        params={
            "fields": "id,text,username,replies{id,username}",
            "limit": 25,
            "access_token": token,
        },
        timeout=25,
    )
    data = resp.json()
    if resp.status_code >= 400 or "error" in data:
        raise RuntimeError(f"Failed fetching comments for {media_id}: {data}")
    return data.get("data", [])


def post_reply(comment_id: str, message: str, token: str) -> dict:
    resp = requests.post(
        f"{IG_API_BASE}/{comment_id}/replies",
        data={"message": message, "access_token": token},
        timeout=25,
    )
    data = resp.json()
    if resp.status_code >= 400 or "error" in data:
        raise RuntimeError(f"Failed replying to comment {comment_id}: {data}")
    return data


def main() -> None:
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing IG_ACCESS_TOKEN environment variable.")

    if not REEL_PYQS_PATH.exists():
        print("reel_pyqs.json not found. Exiting.")
        return

    reel_pyqs = json.loads(REEL_PYQS_PATH.read_text(encoding="utf-8"))
    posted_reels = [q for q in reel_pyqs if q.get("posted") and q.get("ig_media_id")]
    if not posted_reels:
        print("No posted Reels with ig_media_id found yet.")
        return

    recent_reels = posted_reels[-10:]
    total_replied = 0
    max_replies_per_run = 15

    for quiz in recent_reels:
        media_id = str(quiz["ig_media_id"])
        pool = ReplyStylePool()
        print(f"Checking comments on {quiz['id']} (Media ID: {media_id})...")
        try:
            comments = fetch_comments(media_id, token)
        except Exception as exc:
            print(f"Warning: {exc}")
            continue

        for c in comments:
            if total_replied >= max_replies_per_run:
                print("Reached max replies cap for this run. Stopping cleanly.")
                return

            username = (c.get("username") or "").strip().lower()
            if username == OWN_USERNAME:
                continue

            existing_replies = (c.get("replies") or {}).get("data", [])
            already_replied = any(
                (r.get("username") or "").strip().lower() == OWN_USERNAME
                for r in existing_replies
            )
            if already_replied:
                continue

            comment_text = (c.get("text") or "").strip()
            reply_msg = build_varied_reply(comment_text, quiz, pool)
            print(f"Replying to @{username} ('{comment_text}') -> '{reply_msg}'")
            try:
                res = post_reply(c["id"], reply_msg, token)
                print(f"Replied! Reply ID: {res.get('id')}")
                total_replied += 1
                time.sleep(random.uniform(3.0, 7.0))
            except Exception as exc:
                print(f"Error replying to {c['id']}: {exc}")

    print(f"Done! Total new replies sent: {total_replied}")


if __name__ == "__main__":
    main()
