# Deploy Your Offer Agent to the Web — Step by Step

**Goal:** Get your Offer Agent live at a public URL like `https://estevan-offer-agent.onrender.com` so you can open it on your iPhone without running anything on your laptop.

**Time needed:** ~20–30 minutes the first time. After that, any code change auto-deploys in ~3 minutes.

**Cost:** $0 — Render's free tier covers this. (Free apps sleep after 15 min idle and take ~30 sec to wake up. Fine for personal use.)

**You'll need:** an email address and a phone for 2FA. No credit card required for free tier.

---

## Part 1 — Put the code on GitHub (10 min)

GitHub is where your code "lives." Render will pull from there.

### Step 1. Make a GitHub account

1. Open https://github.com/signup in your browser.
2. Enter an email, password, and a username (e.g. `estevan-ouellet` — this becomes part of your repo URL).
3. Verify your email (GitHub will send a code).
4. When asked "How many team members?" pick **Just me**.
5. Pick the **Free** plan.

If you already have a GitHub account, skip to Step 2.

### Step 2. Create a new repository

A "repository" (repo) is just a folder of code on GitHub.

1. Once logged in, click the **+** icon at the top-right, then **New repository**.
2. Repository name: `estevan-offer-agent`
3. Description (optional): `AI voice agent for NSAR Form 400`
4. Visibility: **Public** (Render's free tier requires public repos. Your code will be visible — which is fine, there are no secrets in it. The blank Form 400 and any client data you add are the only sensitive parts, and `clients.json` is excluded by `.gitignore`.)
5. **Do NOT** tick "Add a README," "Add .gitignore," or "Choose a license." Leave all three unchecked — our bundle already has what's needed.
6. Click **Create repository**.

You'll land on an empty repo page with setup instructions. Ignore the command-line stuff. We're going to upload through the browser.

### Step 3. Upload the deploy bundle

1. On that empty-repo page, find the link **"uploading an existing file"** near the top (it's in the line "Quick setup — if you've done this kind of thing before … uploading an existing file"). Click it.
2. A drag-and-drop box appears.
3. Unzip `estevan-offer-agent-deploy.zip` on your computer (the zip I made alongside this guide). You'll see a folder containing `Dockerfile`, `backend_server.py`, `Form_400_blank.pdf`, etc.
4. Select **all the files inside the folder** (not the folder itself) and drag them into the GitHub upload box. Wait for every file to show a green check.
5. Scroll down to **Commit changes**. Leave the default message ("Add files via upload") or type `Initial deploy`.
6. Click **Commit changes**.

Your repo now shows all the files. You're done with GitHub for now.

---

## Part 2 — Deploy on Render (10 min)

Render turns your repo into a running web server.

### Step 4. Make a Render account

1. Open https://render.com in your browser.
2. Click **Get Started** (top right).
3. Choose **Sign up with GitHub**. This is the easy path — Render will read your repo automatically.
4. GitHub will ask "Authorize Render?" — click **Authorize**.
5. Fill in your name if prompted.

### Step 5. Create the web service

1. On the Render dashboard, click **+ New** (top right) → **Blueprint**.
   - "Blueprint" tells Render to read the `render.yaml` file in your repo and set everything up automatically.
2. Under **Connect a repository**, click **Connect GitHub** if not already connected, then click **Configure account** and grant Render access to the `estevan-offer-agent` repo (you can pick "All repositories" or just this one).
3. Find `estevan-offer-agent` in the repo list and click **Connect**.
4. Render reads `render.yaml` and shows a summary: one service named `estevan-offer-agent`, Docker environment, free plan.
5. Blueprint name: leave as `estevan-offer-agent` or whatever you like.
6. Click **Apply**.

### Step 6. Wait for the first build (5–8 min)

Render now:
1. Downloads your code.
2. Builds the Docker image (installs Python, qpdf, all the libraries).
3. Starts the server.
4. Verifies `/health` returns OK.

You'll see log lines streaming. When it's done, a green **Live** badge appears at the top of the page, next to a URL like:

```
https://estevan-offer-agent-xxxx.onrender.com
```

(The `-xxxx` part is a random suffix Render adds. Copy the full URL.)

### Step 7. Open it on your phone

1. Open Safari on your iPhone.
2. Paste the Render URL.
3. You should see the **Offer Agent front-screen mockup** — the mic button and the client search box.
4. Tap **Add to Home Screen** from the share menu so it behaves like an app.

You're live.

---

## What to do next

### Test the PDF fill

1. Open `https://your-url.onrender.com/docs` — this is Swagger, an auto-generated API console.
2. Expand `POST /api/fill`.
3. Click **Try it out**.
4. Paste the sample offer JSON (you can grab it from the backend code's docstring or ask me for a copy).
5. Click **Execute**. You'll get back a filled PDF.

### Test closing-date validation

Same `/docs` page:
1. Expand `POST /api/validate_closing`.
2. Try `{"date": "2026-06-20"}` (a Saturday) and see the alternatives.

### Connecting the voice layer

The browser UI currently has the mic button wired up only for the visual mockup. The next step is:
1. Hook the Web Speech API (built into Safari) to the mic button for speech-to-text.
2. Route each turn through the Claude Messages API using `System_Prompt_Offer_Agent.md`.
3. When the conversation ends, POST the offer JSON to `/api/fill`.

That's the next build session. Ping me when you're ready.

---

## Troubleshooting

**"Build failed" on Render.**
Click the **Logs** tab and scroll up to find the red error line. Most common: a typo or missing file from the upload. Re-upload any missing files to GitHub (Part 1, Step 3 — you can drag them in again), then on Render click **Manual Deploy → Deploy latest commit**.

**URL loads but shows "Application failed to respond" / 502.**
Render is still starting up, or the app crashed. Check **Logs** for a Python traceback. Most likely the Form_400_blank.pdf didn't upload. Verify it's in the repo root on GitHub.

**Everything works, but the site is slow to load the first time each morning.**
That's Render's free tier sleeping. It wakes in ~30 seconds on first request. Upgrade to the **Starter** plan ($7/mo) to keep it warm 24/7. For personal use, the free tier is usually fine.

**I want to change the code.**
Easiest way: edit the file on GitHub (click the file, click the pencil icon, edit, commit). Render sees the commit within ~30 seconds and redeploys automatically — takes ~3 minutes.

**I want to lock it down so only I can use it.**
For the MVP there's no auth. If you want to keep it private: open `backend_server.py` and add a hardcoded API key check, or put the whole thing behind Cloudflare Access. Ask me when you get there.

---

## What's in the bundle

| File | Purpose |
|------|---------|
| `backend_server.py` | FastAPI web server |
| `form_400_filler.py` | PDF filler (the v10 logic that handles checkboxes correctly) |
| `closing_date_validator.py` | Weekend / NS holiday check |
| `client_store.py` | Client database with fuzzy search |
| `AI_Front_Screen_Mockup.html` | The UI you see at the root URL |
| `Form_400_blank.pdf` | The blank NSAR Form 400 (renamed from "Edible version.pdf") |
| `requirements.txt` | Python dependencies |
| `Dockerfile` | Tells Render how to build the image |
| `render.yaml` | Tells Render what kind of service to run |
| `.gitignore` | Keeps local caches and `clients.json` out of the repo |

That's it. Good luck — ping me if any step doesn't match what you're seeing.
