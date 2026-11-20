#!/usr/bin/env python3
"""
Smart All-Scenario Official Meta API Auto-Reply Bot (@ssc1.daily) - v2
----------------------------------------------------------------------
Handles every real-world Instagram comment scenario cleanly at Rs 0/month:
  1. Option guess (A/B/C/D or answer text) -> non-repeating short/detailed reply
  2. Mini Mock score (3/3, 2/3, 1/3, 0/3)  -> tailored encouragement
  3. "Why / Explain / Wrong / Galat"       -> verified NCERT source + explanation
  4. Tagging a friend (@username)          -> fun study-buddy challenge reply
  5. Praise / Thanks / Positive Emojis     -> natural short gratitude + occasional follow nudge
  6. General exam doubts / Spam / Hate / Unknown text -> SKIPPED safely for manual review
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
CAROUSEL_PYQS_PATH = ROOT_DIR / "pyqs.json"
OWN_USERNAME = "ssc1.daily"

IG_API_BASE = (
    "https://graph.instagram.com/v21.0"
    if os.environ.get("IG_ACCESS_TOKEN", "").startswith("IG")
    else "https://graph.facebook.com/v21.0"
)

RIGHT_TEMPLATES = [
    "Yes, correct.",
    "Sahi hai.",
    "Right, {ans} hi hoga.",
    "Correct! {ans} is right - follow @ssc1.daily for daily SSC PYQs.",
    "Bilkul sahi. Daily aise hi PYQs ke liye follow kar lena.",
    "Spot on - {expl}",
    "Correct answer. {expl}",
    "Exactly right! {expl} Follow @ssc1.daily for daily practice.",
]

WRONG_TEMPLATES = [
    "Nahi, {ans} hoga.",
    "Close, correct answer {ans} hai.",
    "Actually {ans} hai sahi.",
    "Tricky question tha - correct answer {ans} hai. Daily SSC PYQs ke liye follow kar sakte ho.",
    "Close! {ans} hoga. Follow @ssc1.daily for more such exam traps.",
    "Close! Correct answer is {ans} - {expl}",
    "Actually {ans} hoga. {expl}",
    "Good try - {ans} is correct. {expl}",
]

PRAISE_TEMPLATES = [
    "Thanks!",
    "Thank you, glad it helped.",
    "Thanks! Follow @ssc1.daily for daily SSC CGL PYQs.",
    "Appreciate it! Daily 2 new PYQ traps aate hain, follow kar sakte ho.",
    "Glad you liked it - save kar lena quick revision ke liye.",
]

TAG_BUDDY_TEMPLATES = [
    "Let's see if they get it right!",
    "Dekhte hain aapka study partner sahi bata pata hai ya nahi.",
    "Good challenge - let's see their guess!",
]

EXPLAIN_TEMPLATES = [
    "Verified from {src} - {expl}",
    "{ans} is correct ({src}). {expl}",
]

SCORE_3_TEMPLATES = [
    "3/3! Solid preparation, keep it up.",
    "Full 3/3 - strong accuracy. Follow @ssc1.daily for the next Mini Mock.",
    "Nice 3/3 score! Ready for Tier-1.",
]

SCORE_2_TEMPLATES = [
    "2/3 is solid, almost there. Save Slide 4 for the missed one.",
    "Good 2/3 score! Next mock me 3/3 pakka.",
]

SCORE_LOW_TEMPLATES = [
    "No worries - save Slide 4 for 1-minute revision, next mock better jayega.",
    "That's why daily practice helps. Revise Slide 4 once and you won't miss it in the exam.",
]

SPAM_OR_ABUSE_WORDS = {
    "http://", "https://", "www.", ".com", "promo", "promote", "dm me",
    "follow back", "f4f", "l4l", "check my profile", "buy followers",
    "crypto", "forex", "betting", "casino", "fake", "scam", "trash",
    "bekar", "bakwas", "chutiya", "mc", "bc", "stupid", "idiot", "useless",
}

EXPLAIN_TRIGGER_WORDS = {
    "why", "explain", "kaise", "kyu", "kyun", "how", "wrong", "galat",
    "proof", "source", "ncert", "sure", "really",
}

PRAISE_WORDS = {
    "nice", "good", "great", "awesome", "helpful", "best", "super", "superb",
    "amazing", "thanks", "thank", "shukriya", "mst", "mast", "badhiya",
    "badiya", "informative", "useful", "op", "love", "wow", "brilliant",
}

POSITIVE_EMOJI_RE = re.compile(r"^[\s🔥❤️💯👏🙌👍✅😍👌🎯📚✨💪🙏]+$")


def extract_option_letter(text: str) -> str | None:
    cleaned = text.strip().lower()
    # Avoid misreading long sentences containing the article "a"
    if len(cleaned.split()) > 6:
        m = re.search(r"(?:option|ans(?:wer)?|correct(?:\s+is)?)\s*[:=-]?\s*\(?([abcd])\)?", cleaned)
        return m.group(1) if m else None
    m = re.search(
        r"(?:^|[\s(])(?:option\s+|ans(?:wer)?\s*[:=-]?\s*)?([abcd])(?:[\s).!?:,]|$)",
        cleaned,
    )
    return m.group(1) if m else None


def extract_correct_letter(correct_answer: str) -> str | None:
    m = re.search(r"\(([a-dA-D])\)", correct_answer)
    return m.group(1).lower() if m else None


class ReplyStylePool:
    def __init__(self) -> None:
        self.base_map = {
            "right": RIGHT_TEMPLATES,
            "wrong": WRONG_TEMPLATES,
            "praise": PRAISE_TEMPLATES,
            "tag": TAG_BUDDY_TEMPLATES,
            "explain": EXPLAIN_TEMPLATES,
            "score_3": SCORE_3_TEMPLATES,
            "score_2": SCORE_2_TEMPLATES,
            "score_low": SCORE_LOW_TEMPLATES,
        }
        self.pools = {k: random.sample(v, len(v)) for k, v in self.base_map.items()}

    def pick(self, bucket: str, ans: str = "", expl: str = "", src: str = "") -> str:
        if not self.pools[bucket]:
            self.pools[bucket] = random.sample(self.base_map[bucket], len(self.base_map[bucket]))
        tpl = self.pools[bucket].pop()
        return tpl.format(ans=ans, expl=expl, src=src).replace("—", "-")


def classify_and_build_reply(
    comment_text: str, quiz: dict, pool: ReplyStylePool, is_carousel: bool = False
) -> str | None:
    """Returns a natural reply string, or None to safely skip for manual admin review."""
    raw = comment_text.strip()
    low = raw.lower()
    if not raw:
        return None

    # 1. Safety filter: skip spam, links, promo, or abusive comments
    if any(bad in low for bad in SPAM_OR_ABUSE_WORDS):
        return None

    # 2. Mini Mock Carousel score comments (e.g., "3/3", "2/3", "1/3", "0/3")
    if is_carousel:
        score_m = re.search(r"\b([0-3])\s*/\s*3\b", low)
        if score_m:
            s = int(score_m.group(1))
            if s == 3:
                return pool.pick("score_3")
            if s == 2:
                return pool.pick("score_2")
            return pool.pick("score_low")

    correct_ans = quiz.get("correct_answer", "").strip().replace("—", "-")
    explanation = quiz.get("explanation", "").strip().replace("—", "-")
    source = quiz.get("verified_source", "Official SSC PYQ & NCERT").strip().replace("—", "-")
    if not explanation and quiz.get("revision_notes"):
        n0 = quiz["revision_notes"][0]
        explanation = f"{n0.get('label', '')}: {n0.get('detail', '')}".strip(": ").replace("—", "-")

    # 3. Tagging a friend (e.g., "@rohit_sharma" or "@friend solve this")
    if re.match(r"^@[a-zA-Z0-9._]+(\s+@[a-zA-Z0-9._]+)*$", raw):
        return pool.pick("tag")

    # 4. Option guess or answer text (only for single-question Reels)
    if not is_carousel:
        correct_letter = extract_correct_letter(correct_ans)
        guessed_letter = extract_option_letter(raw)
        if guessed_letter and correct_letter:
            # Make sure it's not a general question like "a question about syllabus?"
            if "?" not in raw:
                bucket = "right" if guessed_letter == correct_letter else "wrong"
                return pool.pick(bucket, ans=correct_ans, expl=explanation, src=source)

        ans_core = re.sub(r"^\([a-dA-D]\)\s*", "", correct_ans).lower()
        if ans_core and len(ans_core) >= 4 and ans_core in low and "?" not in raw:
            return pool.pick("right", ans=correct_ans, expl=explanation, src=source)

        # 5. Asking "why / explain / wrong / galat" about the Reel's answer
        words = set(re.findall(r"[a-zA-Z]+", low))
        if words & EXPLAIN_TRIGGER_WORDS and explanation:
            return pool.pick("explain", ans=correct_ans, expl=explanation, src=source)

    # 6. General question mark (e.g., "Sir SSC CGL exam date kab hai?") -> skip for manual reply
    if "?" in raw:
        return None

    # 7. Clear praise / gratitude / positive emojis
    words = set(re.findall(r"[a-zA-Z]+", low))
    if POSITIVE_EMOJI_RE.match(raw) or (words & PRAISE_WORDS):
        return pool.pick("praise", ans=correct_ans, expl=explanation, src=source)

    # 8. Anything unrecognized -> skip safely rather than sending an awkward canned reply
    return None


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


def like_comment(ig_user_id: str, comment_id: str, token: str) -> None:
    """Best-effort Like on a comment via official Meta User Likes API (requires instagram_manage_engagement)."""
    if not ig_user_id or token.startswith("IG"):
        return
    try:
        resp = requests.post(
            f"https://graph.facebook.com/v27.0/{ig_user_id}/likes",
            data={"comment_id": comment_id, "access_token": token},
            timeout=20,
        )
        if resp.status_code < 400:
            print(f"Liked comment {comment_id}!")
        else:
            print(f"Like skipped (add instagram_manage_engagement permission if needed): {resp.text}")
    except Exception as exc:
        print(f"Like skipped: {exc}")


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


def collect_recent_posts() -> list[tuple[str, dict, bool]]:
    """Returns list of (media_id, quiz_dict, is_carousel) deduplicated by media_id."""
    seen: set[str] = set()
    items: list[tuple[str, dict, bool]] = []

    if REEL_PYQS_PATH.exists():
        reels = json.loads(REEL_PYQS_PATH.read_text(encoding="utf-8"))
        for q in [x for x in reels if x.get("posted") and x.get("ig_media_id")][-20:]:
            mid = str(q["ig_media_id"])
            if mid not in seen:
                seen.add(mid)
                items.append((mid, q, False))

    if CAROUSEL_PYQS_PATH.exists():
        carousels = json.loads(CAROUSEL_PYQS_PATH.read_text(encoding="utf-8"))
        for q in [x for x in carousels if x.get("posted") and x.get("ig_media_id")][-15:]:
            mid = str(q["ig_media_id"])
            if mid not in seen:
                seen.add(mid)
                items.append((mid, q, True))

    return items


def main() -> None:
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    ig_user_id = os.environ.get("IG_USER_ID", "").strip()
    if not token:
        raise RuntimeError("Missing IG_ACCESS_TOKEN environment variable.")

    posts = collect_recent_posts()
    if not posts:
        print("No posted Reels or Carousels with ig_media_id found yet.")
        return

    total_replied = 0
    max_replies_per_run = 15

    for media_id, quiz, is_carousel in posts:
        pool = ReplyStylePool()
        kind = "Carousel" if is_carousel else "Reel"
        print(f"Checking comments on {kind} {quiz['id']} (Media ID: {media_id})...")
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
            if any((r.get("username") or "").strip().lower() == OWN_USERNAME for r in existing_replies):
                continue

            comment_text = (c.get("text") or "").strip()
            reply_msg = classify_and_build_reply(comment_text, quiz, pool, is_carousel=is_carousel)
            if not reply_msg:
                print(f"Skipped @{username} ('{comment_text}') for manual review.")
                continue

            print(f"Replying to @{username} ('{comment_text}') -> '{reply_msg}'")
            try:
                like_comment(ig_user_id, c["id"], token)
                time.sleep(random.uniform(1.0, 2.2))
                res = post_reply(c["id"], reply_msg, token)
                print(f"Replied! Reply ID: {res.get('id')}")
                total_replied += 1
                time.sleep(random.uniform(3.0, 7.0))
            except Exception as exc:
                print(f"Error replying to {c['id']}: {exc}")

    print(f"Done! Total new replies sent: {total_replied}")


if __name__ == "__main__":
    main()
