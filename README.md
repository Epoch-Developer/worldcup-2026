# Kelly Family World Cup 2026 — self-hosted tracker

A standings page that updates itself four times a day, with **no dependency on
Claude** once it's running. GitHub does everything: hosts the page (GitHub Pages)
and runs the scheduled update job (GitHub Actions).

## How it works (the 30-second version)

- `data/ledger.json` is the **append-only record** of every confirmed match. Nothing
  is ever overwritten or removed, so a flaky feed can never wipe a banked result.
- `build.py` runs on a schedule: it fetches the live results feed, banks any match
  the feed reports as finished, rebuilds the 48-team table, and regenerates
  `index.html`.
- The GitHub Action commits the updated `ledger.json` + `index.html` back to the repo.
- GitHub Pages serves `index.html` as your public website.

No servers, no API keys, no cost. Pure Python standard library.

### Where the scores come from

Results come from the same public World Cup feed you were already using
(`upbound-web/worldcup-live.json`, with `openfootball/worldcup.json` as a backup).
By default (`CROSS_CHECK = True` near the top of `build.py`) a score is only banked
when **both feeds agree** on the exact scoreline — the "two independent sources"
rule, done with two feeds instead of AI. If the second feed doesn't list a match,
it's still banked from the primary feed. Set `CROSS_CHECK = False` to trust the
primary feed alone.

---

## What you need to do on GitHub (step by step)

You only do steps 1–5 once. After that it runs itself.

### 1. Create the repository
1. Go to https://github.com/new
2. **Repository name:** `kelly-worldcup-2026` (any name is fine)
3. Set it to **Public**. *(GitHub Pages is free for public repos. A private repo
   needs a paid GitHub Pro plan to publish a site. The page only shows football
   standings, so public is usually fine.)*
4. Leave everything else unticked and click **Create repository**.

### 2. Upload these files
1. On the new repo page, click **uploading an existing file** (the link in the
   "Quick setup" box), or go to **Add file -> Upload files**.
2. Drag in the **contents** of this folder — `build.py`, `index.html`, `README.md`,
   the `data` folder, and the `.github` folder. GitHub keeps the folder structure,
   so `.github/workflows/update.yml` and `data/ledger.json` land in the right place.
   *(If drag-and-drop misses the `.github` folder because it's hidden on your
   computer, see "Manual file creation" at the bottom.)*
3. Click **Commit changes**.

### 3. Allow the job to save its updates
1. In the repo, go to **Settings -> Actions -> General**.
2. Scroll to **Workflow permissions**.
3. Select **Read and write permissions**, then **Save**.
   *(This lets the scheduled job commit the updated standings back to the repo.)*

### 4. Turn on the website
1. Go to **Settings -> Pages**.
2. Under **Build and deployment -> Source**, choose **Deploy from a branch**.
3. Branch: **main**, folder: **/ (root)**. Click **Save**.
4. Wait ~1 minute. Your site will be live at:
   `https://YOUR-USERNAME.github.io/kelly-worldcup-2026/`

### 5. Do a test run
1. Go to the **Actions** tab. If GitHub asks you to enable workflows, click the
   green button to confirm.
2. Click **Update World Cup tracker** in the left list.
3. Click **Run workflow -> Run workflow** (this is the manual trigger).
4. It runs in under a minute. A green tick means success. Refresh your Pages URL
   and you should see the latest standings with a fresh "Last updated" time.

That's it. From now on it updates automatically.

---

## After it's working

- **Schedule:** runs at 06:00, 12:00, 18:00 and 00:00 Irish time. The times live in
  `.github/workflows/update.yml` as UTC cron lines with comments — edit them there
  if you want different times. GitHub sometimes starts scheduled jobs a few minutes
  late under load; that's normal.
- **You can stop the Claude scheduled task now.** This repo fully replaces it.
- **Manual refresh** any time: Actions tab -> Run workflow.
- **Fixing a wrong score:** edit `data/ledger.json` directly on GitHub (pencil icon),
  correct the numbers, commit. The next run rebuilds the table from it.
- **Heads-up:** GitHub disables scheduled workflows after 60 days with zero repo
  activity. Irrelevant for a 5-week tournament, but if it ever pauses, open the
  Actions tab and re-enable it.

## Folder structure
```
kelly-worldcup-2026/
├─ .github/workflows/update.yml   # the 4x-daily scheduled job
├─ data/ledger.json               # append-only record of confirmed matches
├─ build.py                       # fetch + merge + rebuild the page
├─ index.html                     # the published website (auto-generated)
└─ README.md                      # this file
```

## Manual file creation (only if drag-and-drop skipped the .github folder)
On the repo page: **Add file -> Create new file**. In the filename box, type
`.github/workflows/update.yml` — typing the slashes creates the folders. Paste the
contents and commit. Do the same for `data/ledger.json` if needed.

## Running it on your own computer (optional)
```
python build.py               # full update (needs internet)
python build.py --render-only # just rebuild index.html from the ledger
```
