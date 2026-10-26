# After-Action Report: BoulderPublicData review-and-fix sprint, 2026-10-26 (03:05–15:27 UTC)

## 1. Summary

This sprint ran across three repositories:
- **Election-Results:** moved the Statement of Votes (SoV) outputs.
- **Election-Results and Cast-Vote-Records:** a full code review that filed 39 issues, then fixes for all of them in eight stacked PRs, merged in order.
- **Cast-Vote-Records:** added County source pages, records-request release dates and a cheaper CI reconcile job.
- **City-Council-Minutes:** fixed late-arrival vote inference and kept non-members off the roll call.

The fixes held up under independent checking. Recounts from the raw files, done with a second parser, matched every changed number: 233 and 330 out-of-order merges, 1,012 redacted ballots, Neguse 51,310, and the SoV to the vote. Nothing was reverted.

The costs were in time and steering, not correctness. One delegated agent ran for about 3 hours of active time plus a 7-hour stall. Much of that was re-running a 20–30 minute notebook that a rename-only change didn't need. The user had to ask for an ETA and for options. A revision from the earlier AAR, an output-directory override for long runs, was applied in one repo only. The stop-hook interruptions it was meant to stop came back in a sibling repo.

The highest-leverage revisions:
- port the long-run output override to every pipeline repo, and to the data-liberation skill, which owns the pattern;
- write down in each repo which checks a change actually needs, with their run times, so delegated agents stop paying for checks that prove nothing.

## 2. Scope reviewed

- **Window:** from the "revise the directory structure" request (2026-10-26 03:05 UTC) to the "write an AAR" request (15:27 UTC).
- **Ref ranges:**
  - Election-Results: `fc40bf3..dcdb4ee`
  - Cast-Vote-Records: `5e99680..4d99745`
  - City-Council-Minutes: `743a1ba..655e299`
- **Evidence:**
  - **Commits:** 16 non-merge (7 Election-Results, 7 Cast-Vote-Records, 2 City-Council-Minutes).
  - **PRs:** 11, all merged: Election-Results #15 and #36–#39, Cast-Vote-Records #25–#29, City-Council-Minutes #3.
  - **Issues:** 39 filed and closed (Election-Results #16–#35, Cast-Vote-Records #6–#24).
  - **CI:** read through the GitHub MCP tools, since `gh` was not authenticated. Every PR head was green before its merge.
  - **Sessions:** one main session, with 2 compactions and 4 user turns that steered the work. Plus 5 subagent transcripts:
    - two read-only reviewers (12 and 15 minutes);
    - the Election-Results fixer (87 minutes);
    - the Cast-Vote-Records fixer (183 active minutes, plus a 420-minute stall on an API session limit);
    - the City-Council-Minutes fixer (19 minutes, plus 5 more when resumed).
  - **Not available:** the session collector did not parse the subagent files, so their timelines were read directly. No human review comments exist; the user approved by asking for merges.
- **Earlier AAR:** `docs/aar/AAR_City-Council-Minutes_2026-10-26.md` in City-Council-Minutes (same day, earlier sprint).
- **Rigor level:** `standard`. These are public datasets other people cite, but there's one maintainer and no production service.
- **Intent baseline:**
  - `AGENTS.md` in each of the three repos.
  - The data-liberation skill.
  - The session's standing instructions: the stacked-PR workflow, "verify before you push", the attribution footers, no paid Datalab calls without approval, never `verify=False`.
  - The user's scoping answers for the fixes: keep and flag redacted single ballots, port the parser fix, full key/layout unification, a few PRs per repo.

## 2a. Follow-up on earlier revisions

| ID | Applied? | Recurred? | Verdict |
|---|---|---|---|
| P0-1: list batch/export routes before writing a per-record fetcher (skill) | Skill part not applied | Not exercised. The County CVRs are direct links, and the records portal needs a login, which was checked before any download attempt. | Carry forward (skill) |
| P0-2: check the spend limit; buy the decision set first | Project part applied (`datalab._targets`, gotcha 11) | No. The delegation brief carried "no paid Datalab calls", and the agent rebuilt from cache. | Worked (project). Carry forward (skill). |
| P1-1: output override for long runs (`CCM_DATA_DIR`) | Applied in City-Council-Minutes only | **Yes, in Cast-Vote-Records.** Two "uncommitted changes" stop-hook demands came during a 15-minute pipeline run, and one run was killed and restarted. | **Failed: scoped too narrowly.** Re-diagnosed in §5.2, superseded by P0-1. |
| P1-2: impossible values in the contract, implausible ones as audit flags (skill) | Skill part not applied | No. The roster fix wrote non-members to `excluded_roll_call.csv` instead of failing the build. | Carry forward (skill), low priority |
| P2-1: check reference disagreements against the source and record verdicts | Project habit present | No. Two new verdicts were recorded in `adjudications.csv` (`reference_error`, `pipeline_fixed`). | Worked (project). Carry forward (skill). |

## 3. What the agent was supposed to do (Q1)

- **Repo definitions:**
  - Every `AGENTS.md` says originals are immutable, provenance is a sidecar, outputs are regenerated by the pipeline and checked by `reconcile`, and ruff and pytest run before a PR.
  - City-Council-Minutes gotcha 10 tells long runs to write outside the repo when a commit-on-stop hook is active.
  - Neither Election-Results nor Cast-Vote-Records has that gotcha or an override.
- **Session rules:**
  - Fix all issues as stacked PRs per repo (accuracy → pipeline → docs → unify).
  - Prove each change before pushing: reproduce, run the fast checks, re-read the diff.
  - Don't merge without being asked. Push only to the session branch.
  - No paid API calls without approval. Use American English.
- **User decisions** that bounded the fixes: the redaction rule, porting the 2008/2010 parser fix, full key/layout unification, and "a few PRs per repo".

## 4. What actually happened (Q2)

- **03:05–03:14: SoV move (Election-Results #15).** One commit, merged on request.
- **03:19–03:37: review.** Two read-only reviewers ran in parallel. Then 20 and 19 issues were filed with tracking, cross-repo and checklist issues.
- **03:49: fix phase.** Two fixer agents ran in parallel.
  - **Election-Results:** four PRs in 87 minutes, data regenerated, CI green.
  - **Cast-Vote-Records:** two PRs were up when the agent hit an API session limit at 05:26. It stalled 7 hours and resumed at 12:26 on a manual nudge. Its active time went largely to two full end-to-end runs of `clusters.ipynb`, about 21 and 31 minutes each, to prove reproducibility, plus 10-minute waits.
  - **13:01: steering.** The user asked "ETA or options to split across agents?". The reply skipped a third full notebook run for the rename-only PR, ran a smoke test instead, and started reviewing the first two PRs in parallel. Both remaining PRs were up by 13:58.
- **Review of the fixes.** Every changed count was rechecked from the raw files with separate code:
  - **Election-Results:** SOS retention totals, the 2008 president totals against SOS, and a PDF page.
  - **Cast-Vote-Records:** the redaction split, the Neguse total, per-column mark totals, and the out-of-order merges, re-derived with an independent walk of the raw sheets.
  - Every recheck matched.
- **14:04–14:06: merges.** Eight PRs were merged in stack order. The next PR in each stack was retargeted to `main` before its merge. No conflicts.
- **14:11: follow-up requests.**
  - **Branch deletion:** refused with HTTP 403, because the session can push only its own branch.
  - **CI downloads:** limited by a separate path-filtered, cached reconcile workflow.
  - **Late arrivals:** delegated. Only 3 of 62 declined motions were recovered. The brief's plain rule was wrong on 3 of the first 6 motions until the agent added a mover/seconder guard.
  - **Sources:** the County by-year pages were checked, and the four public files matched byte for byte.
- **14:26: records request.** A saved records-portal page gave the request number and the 2023-12-19 release date. Downloading wasn't possible because the attachments need a logged-in session. A 15-minute pipeline run was killed and restarted to fold the dates in.
- **14:26–14:32: roster fix.** The resumed City-Council-Minutes agent fixed the non-member roster bug it had found in passing.
- **15:00: last merges.** Cast-Vote-Records #29 and City-Council-Minutes #3 merged.
- **Friction:**
  - **Stop hook:** fired 3 times: two "uncommitted changes" demands during the Cast-Vote-Records run, and one "no remote branch" false alarm.
  - **Tool errors:** about 8 one-off failures:
    - three fetch or tracking errors from single-branch clones;
    - one `pkill` that matched its own shell;
    - one merge call rejected for a 7-character SHA;
    - one push that failed on an LFS lock-verification error and a server 500.

## 5. Gap analysis (Q3)

### 5.1 Delegated agents ran verification that didn't match the change, with no time budget (cost: hours, plus one user intervention)

- **Observation:**
  - The Cast-Vote-Records fixer ran the clustering notebook end to end twice, at 21 and 31 minutes. It was on course to do it again for PR 4, which only renamed paths.
  - Each PR also re-ran the full 15-minute pipeline.
  - Together with the API stall, the four PRs took from 03:55 to 13:58.
  - The user had to ask for an ETA and for options. My earlier estimate, 1½–2½ hours, was wrong by several hours.
  - Once told "smoke-test the load and write cells for a rename-only change", the last two PRs took about 90 minutes together.
- **Root cause: missing.** Neither `AGENTS.md` in Cast-Vote-Records nor the delegation brief said:
  - how long the notebook and pipeline take;
  - which kinds of change need a full run (cluster inputs or code) and which need only a smoke test (paths, docs).
  
  The session rule "prove the change before pushing" was followed literally, at the most expensive level, because nothing said what proof was enough for each kind of change.
- **Why it matters:** every future agent in this repo pays the same 20–30 minutes per notebook run, and many runs will be for non-cluster changes. Writing down the check that fits each kind of change is cheaper than re-deriving it, and it makes ETAs possible.

### 5.2 The long-run output override was fixed in one repo, so the stop-hook interruptions recurred in another (failed earlier revision)

- **Observation:**
  - The earlier AAR's P1-1 added `CCM_DATA_DIR` to City-Council-Minutes.
  - This sprint, Cast-Vote-Records ran its 15-minute pipeline inside the repo three times. The stop hook demanded commits twice mid-run.
  - The response was to commit the code changes and wait. When new provenance facts arrived (the records-request page), a half-finished run had to be killed and restarted.
  - Election-Results has the same layout and no override either.
- **Root cause: the fix's scope was too narrow, not "missing".** The pattern belongs to the data-liberation project shape (`data/` inside the repo, multi-minute regeneration), not to one repo. The earlier AAR proposed it as a project change, and the skill part, which would reach new and sibling repos, was never written.
- **Why it matters:** each stop-hook demand during a run pushes toward committing a half-finished state or a split commit. Each restart costs the full run.

### 5.3 Sibling repos were single-branch clones, so branch work failed in small ways (4 tool errors, 1 false hook alarm)

- **Observation:** `add_repo` clones fetch only the default branch, so these failed:
  - `git fetch origin <branch>` with "couldn't find remote ref" or "Needed a single revision";
  - `git branch -u` with "not a branch";
  - the stop hook reported "no remote branch" for a branch that had been pushed.
  
  Each needed a hand-written refspec.
- **Root cause: missing environment context.** Nothing in the definitions or skills mentions that sibling clones are single-branch, or the one-line fix.
- **Why it matters:** these are cheap failures, but they recur on every multi-repo sprint, and the false hook alarm costs a turn.

### 5.4 Merged branches pile up because two repos don't auto-delete them, and the session can't delete them (1 refused request)

- **Observation:**
  - The user asked to delete the merged branches, and the push was refused with 403.
  - In Cast-Vote-Records, #29's head branch disappeared on merge, which suggests auto-delete is on there.
  - The merged branches are still present in Election-Results (all five `claude/gracious-babbage-b48zcc*`) and in City-Council-Minutes (`claude/gracious-babbage-b48zcc`).
- **Root cause: a tool-config gap between repos, plus an environment limit the agent didn't know about.**
- **Why it matters:** a repository setting removes the chore for every future PR, and the session can't do it anyway.

### 5.5 A fix was promised before it was sized, and the brief encoded an untested rule (low cost)

- **Observation:**
  - `sample_report.md` said attendance notes "could recover many" uninferred votes. The fix recovered 3 of 62.
  - The brief's rule (gap = number of noted members) was wrong on 3 of its first 6 motions. The agent caught this by spot-checking against the minutes and added a guard.
- **Root cause: missing.** The data-liberation skill's audit guidance asks for findings, not for the count of records a proposed fix would touch.
- **Why it matters:** sizing takes one query, and it sets expectations and priorities. Here it would have shown that roll-call extraction errors (21 motions) were the bigger lever.

### 5.6 Smaller items, each happening once

These are recorded without a definition change:
- A `pkill -f` matched its own shell.
- The GitHub merge call needs the full 40-character SHA.
- `git lfs` lock verification fails on this host. Fixed per repo with `lfs.<url>.locksverify false`.
- PR bodies in Cast-Vote-Records had the required footer replaced by the comment-style footer, apparently on the server side. The bodies sent were correct.
- `ruff format --check` would reformat 25 Cast-Vote-Records files. CI only runs `ruff check`, the same as Election-Results, so formatting is unenforced in both. That's a policy choice to make once (P2-2).

## 6. Recommended revisions (Q4)

### [P0-1] Give every pipeline repo an output-directory override, and put the pattern in the skill

- **Target:**
  - Election-Results and Cast-Vote-Records `scripts/config.py` and `AGENTS.md` (new gotcha).
  - data-liberation `SKILL.md` § project skeleton.
- **Root cause:** fix scoped too narrowly (earlier P1-1 recurred).
- **Medium:** tool config (env override) + definition text + skill body.
- **Supersedes:** P1-1 (2026-10-26, City-Council-Minutes).
- **Evidence:**
  - 2 stop-hook "uncommitted changes" demands during Cast-Vote-Records pipeline runs.
  - 1 killed and restarted 15-minute run.
  - Election-Results has the same exposure.
- **Change:**
  - **`scripts/config.py`**, Cast-Vote-Records (`CVR_DATA_DIR`) and Election-Results (`ELECTIONS_DATA_DIR`):
    ```python
    DATA_DIR = Path(os.environ.get("CVR_DATA_DIR", PROJECT_ROOT / "data"))
    ```
  - **`AGENTS.md`** gotcha, both repos:
    > **Long runs and the working tree.** `pipeline` and `clusters.ipynb` take 15–30 minutes and rewrite tracked files as they go. If a commit-on-stop hook or file watcher is active, run against a copy: `cp -r data /tmp/x/ && CVR_DATA_DIR=/tmp/x/data uv run python -m scripts.pipeline`, then copy the outputs back and commit once. A half-finished `data/` should never be committed.
  - **data-liberation `SKILL.md`**, project skeleton:
    > `scripts/config.py` reads `DATA_DIR` from a `<PROJECT>_DATA_DIR` environment variable (default `./data`), so runs that take minutes or hours can write outside the working tree and be committed once.
- **Why it works:** the earlier fix worked where it existed. It failed only where it wasn't. Putting it in the skill makes new and sibling repos start with it.
- **Owner:** auto-applyable (config + gotcha); maintainer review (skill).
- **Status:** Proposed

### [P0-2] Write down which checks each kind of change needs, and how long they take

- **Target:** Cast-Vote-Records `AGENTS.md` → new "Checks by change type" section. A short version goes in Election-Results and City-Council-Minutes `AGENTS.md`.
- **Root cause:** missing.
- **Medium:** definition text. It needs judgment about what a change touches, so it can't be a hook.
- **Evidence:**
  - 2 full notebook runs (21 and 31 minutes) plus a planned third for a rename-only PR.
  - A pipeline run per PR.
  - About 10 hours from start to finish, including a 7-hour stall.
  - One user intervention ("ETA or options to split?").
  - After the instruction to smoke-test, the last two PRs took about 90 minutes.
- **Change** (Cast-Vote-Records):
  > ## Checks by change type
  > Run the cheapest check that can catch a mistake in what you changed, and say which one you ran in the PR.
  >
  > | Change touches | Run | Time |
  > |---|---|---|
  > | docs, comments, recipes | `ruff check .`, `pytest` | < 1 min |
  > | `scripts/` (not the cleaner or loader) | + `reconcile` | ~3 min |
  > | `loader.py`, `cleaner.py`, `sources.py`, originals | + full `pipeline`, then `reconcile --sov` | ~15 min |
  > | paths or keys only (renames) | + the notebook's load and write cells on the new paths (smoke test) | ~2 min |
  > | cluster inputs, `clusters.ipynb` logic, UMAP/HDBSCAN params | + full `nbconvert --execute` (once; a second run only to prove reproducibility after changing seeds or params) | 20–30 min |
  >
  > Long runs: use `CVR_DATA_DIR` (gotcha N) and run them in the background.
- **Why it works:** "prove it before pushing" is a good rule with no exchange rate. This table gives the agent one, so it can do proportionate verification without asking and can give a real ETA.
- **Owner:** maintainer review (one-time).
- **Status:** Proposed

### [P1-1] Make sibling-repo clones fetch every branch

- **Target:** user-level `~/.claude/CLAUDE.md`, or a SessionStart hook for cloud sessions. Plus one line in each repo's `AGENTS.md` under "Working in a cloud session".
- **Root cause:** missing environment context.
- **Medium:** hook (preferred, mechanical) or definition text.
- **Evidence:** 4 fetch or tracking errors and 1 false "no remote branch" stop-hook alarm across Election-Results and Cast-Vote-Records.
- **Change:**
  > After cloning a sibling repository in a cloud session, run `git config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*' && git fetch origin`. Clones added by `add_repo` track only the default branch, so branch fetches, `git branch -u` and the stop hook's push check otherwise fail.

  A hook version is to run that command in every `/home/user/*/` git directory at session start. It is untested; test it before enabling.
- **Why it works:** it removes a whole class of small failures that otherwise come back with every new repo.
- **Owner:** maintainer.
- **Status:** Proposed

### [P1-2] Reconcile at the grain of the published table, and make it able to fail

- **Target:** data-liberation `SKILL.md` § validation, or `discovery-and-audit.md`.
- **Root cause:** missing in the skill. Fixed in both repos this sprint.
- **Medium:** skill body.
- **Evidence:** the review found defects that earlier sprints shipped, because reconcile checked only top-line totals (Election-Results) or couldn't fail at all (Cast-Vote-Records):
  - SOS retention votes 60% missing;
  - 2008 president at 1,005 instead of 171,763;
  - 1,154–1,448 duplicate keys per PDF year;
  - wrong measure pass rates.
  
  Adding contest × candidate reconcile (Election-Results) and a per-column mark check (Cast-Vote-Records) took both to 0 mismatches. The SoV now matches to the vote.
- **Change:**
  > Reconcile at the grain you publish. If the table is contest × candidate × precinct, compare contest × candidate totals with the source's own printed totals, plus structural checks (duplicate keys, mixed option types). Use an independent reader (a second parser) so a shared bug can't pass both sides. Make `reconcile` exit non-zero on a mismatch and run it in CI with path filters and an LFS cache.
- **Why it works:** a top-line check passes when errors cancel or sit below the total. Checking at the published grain is what caught all four defect classes here.
- **Owner:** maintainer review.
- **Status:** Proposed

### [P2-1] Turn on "Automatically delete head branches" in Election-Results and City-Council-Minutes

- **Target:** GitHub repository settings → General → Pull Requests.
- **Root cause:** a tool-config gap between repos. The session can't delete branches itself (403).
- **Medium:** tool config.
- **Evidence:** 1 refused deletion. Six merged branches remain: five in Election-Results, one in City-Council-Minutes. Cast-Vote-Records already deletes them on merge.
- **Change:** enable the setting in both repos, and delete the existing merged branches once.
- **Why it works:** it removes the chore for every future PR.
- **Owner:** repo admin.
- **Status:** Proposed

### [P2-2] Decide whether `ruff format` is enforced

- **Target:** `.github/workflows/tests.yml` in Election-Results and Cast-Vote-Records, or a sentence in each `AGENTS.md`.
- **Root cause:** ambiguous. Lint is enforced, and formatting is neither enforced nor stated as optional.
- **Medium:** tool config.
- **Evidence:** 25 Cast-Vote-Records files would be reformatted.
- **Change:** add `uv run --frozen ruff format --check .` after the lint step, in a PR that runs `ruff format .` once. Or add to `AGENTS.md`: "Formatting is not enforced; don't reformat files you aren't otherwise changing."
- **Owner:** maintainer.
- **Status:** Proposed

### [P2-3] Size a proposed fix before recommending it

- **Target:** data-liberation `discovery-and-audit.md` § findings.
- **Root cause:** missing.
- **Medium:** skill body.
- **Evidence:** the claim "could recover many" became 3 of 62. The plain rule was wrong on 3 of its first 6 motions until a guard was added.
- **Change:**
  > When an audit report recommends a fix, give the number of records it would touch, from a query against the current data, and spot-check five by hand before writing the rule into a brief.
- **Owner:** maintainer review.
- **Status:** Proposed

## 7. Strengths to sustain

- **Independent recounts as the review standard.** Every changed number was rechecked with code that shares nothing with the pipeline:
  - calamine instead of openpyxl;
  - a separate walk of the merge logic;
  - a second look at a PDF page.
  
  Matches were exact: 233/330, 1,012 and 3, 51,310, and the SoV to the vote. This is why eight data-changing PRs could merge in one pass. Keep it as the bar for any PR that changes published counts.
- **Stacked PRs by concern, each with "Data impact" and "Decisions to review" sections.** Reviewers saw before/after tables and the judgment calls up front. Examples: the 2022 DS-38 row, redacted ballots left out of clustering, and the overvote finding. Merging in order with each next PR retargeted to `main` produced no conflicts.
- **Parallel agents for independent repos, and resuming an agent for related follow-up work.** The two reviewers and two fixers ran in parallel. The roster fix went back to the agent that found the bug and took 5 minutes.
- **Hard constraints in delegation briefs held.** "No Datalab or portal calls" and "rebuild from cache" were followed. The earlier P0-2 still works.
- **Spot-checking before trusting a rule.** The late-arrival agent tested its rule against the minutes, found it wrong on 3 of 6 motions, and tightened it instead of shipping it. Codified in P2-3.
- **Reconcile in CI** (Election-Results contest × candidate; Cast-Vote-Records with a path filter and LFS cache) now guards the defect classes the review found.
- **Provenance honesty.** Dates that were never recorded were left blank and marked as upper bounds, not invented. When real dates turned up (the records-request page and the County site), they were added with their source.

## 8. Revision actions — tracking table

Applied after review (2026-10-26): P0-1 (project part), P0-2, P2-1 and P2-2. The P0-1 skill part and the other skill edits remain proposed.

| ID | Pri | Target | Medium | Change | Owner | Status | Check next time |
|---|---|---|---|---|---|---|---|
| P0-1 | P0 | Election-Results/Cast-Vote-Records `config.py`, `AGENTS.md`; data-liberation `SKILL.md` | tool config + definition + skill body | `<PROJECT>_DATA_DIR` override and long-run gotcha in every pipeline repo | auto / maintainer | Applied (project: `CVR_DATA_DIR`, `ELECTIONS_DATA_DIR`; `CCM_DATA_DIR` already existed). Skill part proposed | Stop-hook "uncommitted changes" demands during pipeline runs: 2 → 0. Runs killed and restarted: 1 → 0 |
| P0-2 | P0 | Cast-Vote-Records `AGENTS.md` (short versions in Election-Results and City-Council-Minutes) | definition text | "Checks by change type" table with run times | maintainer | Applied (Cast-Vote-Records full table, Election-Results §10, City-Council-Minutes short table) | Full notebook runs for non-cluster changes: 2 (+1 planned) → 0. User ETA or "split?" questions: 1 → 0 |
| P1-1 | P1 | `~/.claude/CLAUDE.md` or SessionStart hook; `AGENTS.md` note | hook (untested) / definition text | Fetch all branches in sibling clones | maintainer | Proposed | Fetch or tracking errors from single-branch clones: 4 → 0. False "no remote branch" alarms: 1 → 0 |
| P1-2 | P1 | data-liberation `SKILL.md` § validation | skill body | Reconcile at the published grain, with an independent reader; it can fail, and it runs in CI | maintainer | Proposed | Accuracy defects found by a later review that reconcile should have caught: 4 classes → 0 |
| P2-1 | P2 | GitHub settings (Election-Results, City-Council-Minutes) | tool config | Auto-delete head branches | repo admin | Applied by the maintainer in all three repos | Merged branches left after a sprint: 6 → 0 |
| P2-2 | P2 | `tests.yml` or `AGENTS.md` (Election-Results, Cast-Vote-Records) | tool config | Enforce or disclaim `ruff format` | maintainer | Applied: enforced in CI after a one-time reformat (Election-Results 46 files, Cast-Vote-Records 28), listed in `.git-blame-ignore-revs` | Files `ruff format --check` would change: 25 → 0, or a stated policy |
| P2-3 | P2 | data-liberation `discovery-and-audit.md` | skill body | Size a fix and spot-check 5 before briefing it | maintainer | Proposed | Briefed rules corrected after the first spot-check: 1 → 0 |
| (2026-10-26 P0-1, P0-2 skill part, P1-2, P2-1) | — | data-liberation skill | skill body | Carried forward from the earlier AAR | maintainer | Proposed | As in the earlier report |
