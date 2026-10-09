# 3-minute demo script

Works with no API key and no cloud services (built-in planner, temporary in-memory storage). Every step below uses features that exist and were exercised in the browser smoke test.

## Setup (before the demo)

```bash
cd frontend && npm run build
cd ../backend && ./.venv/bin/uvicorn main:app --port 8000
```

Open `http://localhost:8000` (or the Cloud Run URL) on a phone or in a browser at phone width. Use a fresh browser profile so the session starts empty. Optionally pre-load the "Remember a preference" example in a second tab.

## Script

| Time | Do | Say |
|---|---|---|
| 0:00–0:20 | Show the home screen. | "Students plan study time across scattered tools. Chatbots can suggest a timetable, but either can't act or act without asking. CampusPilot plans *and* acts — but nothing changes until you approve it." |
| 0:20–0:35 | Tap **Plan tomorrow's study (demo)**. Point out it only fills the box. Tap **Plan it**. | "I'll ask: two hours of DBMS, one hour of DAA, and I have a project meeting at 4 PM." |
| 0:35–1:05 | Scroll the result: summary, approval card, plan steps. Open one **Technical details**. | "It parsed the subjects and durations, read my schedule, checked the 4 PM slot, and found free slots inside my study window with a 10-minute break. Green steps already ran — they only *read* data. The amber steps would *change* data, so they wait. Under the hood each step has dependencies and uses one of 17 allow-listed tools." |
| 1:05–1:25 | On the approval card, read the three changes. Tap **Approve 3 changes** (a quick double tap is fine). | "This is the safety gate. The approval is tied to my session and a hash of exactly these three changes, it's single-use, and it expires in 15 minutes. Double-tapping can't create duplicates." |
| 1:25–1:45 | Show **What was saved** with "read back and verified"; scroll the steps (all Done). | "It only says 'saved' after reading each item back from storage and checking it matches what I approved." |
| 1:45–2:00 | Tap **Activity** in the bottom bar; expand the workflow; open **Detailed audit log**. | "Every plan, approval and verification is in the timeline and audit log — no parameters or secrets are logged." |
| 2:00–2:30 | Back to **Plan**. Tap **Remember a preference, then plan** → **Plan it**. Show the first step "Save study preference" and the DBMS block in the evening. Point to "Your saved preferences shaped this plan" if shown. Tap **Approve**. Then open **Preferences** to show DBMS · evening saved. | "Memory: 'I prefer DBMS in the evening' is saved — with approval — and the same plan already uses it. I can edit or reset preferences any time; reset needs explicit confirmation." |
| 2:30–2:45 | Tap the status pill in the header. | "It's honest about its state: here the built-in planner is running because no AI key is configured, and storage is temporary. With a Gemini key it plans with Gemini 2.5 Flash, and if Gemini fails it falls back automatically and tells you." |
| 2:45–3:00 | Close. | "CampusPilot: an agent that does the planning work, shows its reasoning, asks before it touches your data, and proves what it did." |

## Fallback paths

- **Gemini configured but failing:** the plan still appears with the note "Built-in planner used". Mention it as a resilience feature.
- **Server restarted mid-demo:** approving shows "This approval is no longer available … Nothing was saved" with **Plan again** — tap it.
- **Ambiguous goal:** type "help me study" to show the clarification card ("CampusPilot needs one more detail").
- **Offline backend:** the red banner explains the server can't be reached and keeps the typed goal.

## Don't claim

- No Google Calendar or other external app integration exists.
- Don't say data is saved permanently unless Firestore is enabled and the status panel shows "Durable (Firestore)".
- Don't say Gemini is running unless the status panel shows "Gemini AI".
