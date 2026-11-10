# After-Action Report: BoulderPublicData follow-up sprint, 2026-10-26 → 2026-11-10

## 1. Summary

This sprint applied the previous AAR's revisions, then ran two rounds of data work.

- **Revisions applied:**
  - Election-Results #41;
  - Cast-Vote-Records #31;
  - City-Council-Minutes #5.
- **New Cast-Vote-Records data:** three originals (2017 Coordinated, 2018 Primary, 2018 General) in #32, plus a change to the cluster figure.
- **Issues:** seven issues drafted by the maintainer were filed and then fixed:
  - Election-Results #42–#46, fixed in #47;
  - Cast-Vote-Records #33–#34, fixed in #35.

All nine PRs merged with green CI and nothing was reverted. Every changed number matched an independent recount.

**The two P0 revisions from the last AAR worked:**
- **Checks-by-change-type table.** It made verification proportionate:
  - a figure-only change re-rendered in about a minute instead of a 28-minute notebook run;
  - primaries with no City of Boulder contests got a smoke test.
  - The maintainer asked no "ETA?" questions this sprint, against one last sprint.
- **`*_DATA_DIR` override.** It was used for every long run.

**Three patterns recurred:**
1. **Delegated agents stalled for hours on the API usage limit.** It happened again (7 h last sprint, about 9 h this one). This time the maintainer had to type "Resume".
2. **Stale local branches from single-branch clones.** They produced two more false "unpushed commits" stop-hook alarms. The previous fix, fetching every branch, was declined, so this report proposes a narrower one.
3. **A `pkill -f` matched its own shell** twice more. Once it aborted a chained background rebuild.

**Highest-leverage revisions:**
- a short "Working in a cloud session" section in each `AGENTS.md`: commit and push at milestones; resume a limit-stalled agent at the reset time; stop background jobs by task ID; reset the branch after a merge;
- a one-line note that `audit` writes `docs/variables.*` into the working tree even under `CVR_DATA_DIR`.

## 2. Scope reviewed

- **Window:** 2026-10-26 15:27 UTC (the "write an AAR" request) → 2026-11-10 14:13 UTC.
- **Ref ranges:**
  - Election-Results `693057f..9a4c4d6`: 4 non-merge commits;
  - Cast-Vote-Records `f0ea412..b41c624`: 17 non-merge commits, 3 authors, including the maintainer's two data commits;
  - City-Council-Minutes `4726375..198b270`: 2 non-merge commits.
- **Evidence:**
  - **PRs:** 9, all merged. Election-Results #41 and #47; Cast-Vote-Records #31, #32 and #35; City-Council-Minutes #5; plus the three AAR PRs from the end of the last sprint.
  - **Issues:** 7 filed and closed. Election-Results #42–#46; Cast-Vote-Records #33–#34.
  - **CI:** read through the GitHub tools; every PR head was green before merge.
  - **Sessions:** the main session (2 compactions, about 25 maintainer turns, 4 stop-hook firings) and 2 subagent transcripts. One subagent stopped on an HTTP 429 usage limit.
  - **Session collector:** it found no rejected tool uses and no interrupts. It mislabeled one task notification as a correction, which I discounted.
- **Earlier AAR:** `docs/aar/AAR_BoulderPublicData_2026-10-26.md`, the same file in all three repos.
- **Rigor level:** `standard`, as before. These are public datasets other people cite, with one maintainer.
- **Intent baseline:**
  - the three `AGENTS.md` files, as revised by #41, #31 and #5;
  - the data-liberation skill;
  - the session's standing rules: verify before pushing, push only to the session branch, merge only when asked, attribution footers, no paid API calls without approval.
  - There is no user-level `CLAUDE.md` in this container.

## 2a. Follow-up on earlier revisions

| ID | Applied? | Recurred? | Verdict |
|---|---|---|---|
| P0-1 `*_DATA_DIR` override + long-run gotcha | Yes: Election-Results, Cast-Vote-Records (project); skill text handed over | Partly. All 4 long runs used a copy. 1 stop-hook "uncommitted changes" alarm came from a file the override doesn't cover (`docs/variables.*`, see §5.3). 1 run was restarted, because a new original arrived mid-run, not because of the hook. | **Worked**, with one gap (§5.3) |
| P0-2 checks by change type | Yes, all three repos | No. Figure-only change re-rendered from saved CSVs (~1 min). Primaries smoke-tested. The 2017/2018 additions got the one full notebook run the table calls for (28 min). 0 ETA or "split?" questions (was 1). | **Worked**. Keep it (§7). |
| P1-1 fetch every branch in sibling clones | **Declined** by the maintainer ("not fetch every branch") | Yes: 1 fetch failure ("couldn't find remote ref"), 2 false stop-hook alarms ("12 unpushed", "1 unpushed"), 1 push needing a hand-built lease | **Re-diagnosed.** The cost now comes from stale *local* branches after auto-delete, not from missing remote refs. Superseded by P1-1 below. |
| P1-2 reconcile at the published grain | Yes (project); skill text handed over | No. The new aggregate side table and SoV overlays reconcile at contest × choice. The new failing SoV check flagged exactly the documented differences. | **Worked** |
| P2-1 auto-delete head branches | Yes, set by the maintainer in all three repos | No for new merges: #47's and #35's branches were deleted on merge. Election-Results still has 4 merged `claude/gracious-babbage-b48zcc-*` branches from before the setting. | **Worked**. One-time cleanup outstanding (P2-2 below). |
| P2-2 `ruff format` enforced | Yes, CI check plus one-time reformat | No. 0 format failures across 6 PRs. | **Worked** |
| P2-3 size a fix, spot-check before briefing | Yes (project); skill text handed over | No. The maintainer's drafted issues carried sizes. The Election-Results agent checked #44's claim against the data before applying it, and found the issue named the wrong precinct group. | **Worked** |
| Carried skill edits (2026-10-26 earlier AAR) | Handed over as paste-ready text | Not exercised | Carry forward |

## 3. What the agent was supposed to do (Q1)

- **Verification:**
  - prove changes before pushing, at the level the "Checks by change type" table sets;
  - unrelated outputs byte-identical;
  - independent recounts for data changes.
- **Long runs:** against a `*_DATA_DIR` copy, committed once.
- **Session rules:**
  - push only to `claude/gracious-babbage-b48zcc`;
  - open ready PRs;
  - merge only when asked;
  - footers and trailers on everything;
  - American English.
- **Maintainer decisions this sprint:**
  - key the Presidential Primary `2024-presidential-primary`;
  - make the SoV check fail on mismatch;
  - correct, not just document, the Louisville double count;
  - leave primaries out of the cluster figure.

## 4. What actually happened (Q2)

- **10-26: applying the last AAR's revisions.** Merged the three AAR PRs, then applied P0-1, P0-2, P1-2 (project), P2-2 and P2-3 (project) in Election-Results #41, Cast-Vote-Records #31 and City-Council-Minutes #5. The maintainer set auto-delete on all three repos.
- **10-30: new Cast-Vote-Records originals.** The maintainer pushed two CSV originals to `main`, then mid-turn a third (2018 General).
  - The loader gained CSV support and a new aggregate rule.
  - The full rebuild ran on a copy. It was stopped once to include the late 2018 General file.
  - Records-request numbers and release dates arrived in three follow-up messages and were folded in by re-cleaning only the affected elections (~3 min each), not a full rerun.
  - Results: reconcile ok for 11 elections; 2017 and 2018 General equal the SoV exactly; 8 existing elections byte-identical.
- **10-30: cluster figure.** "Skip the primaries in the small multiples" was handled per the checks table, by re-rendering from saved cluster CSVs with no re-clustering. The maintainer then saw the old figure on GitHub; it was a cached view, and the bytes served were confirmed correct.
- **11-10: the drafted issues.**
  - The maintainer pasted seven drafted issues. Two claims were spot-checked against `main`, all seven were filed, and one overstatement (#33) was flagged.
  - "Fix all the new issues": three design forks were put to the maintainer in one question set, then two agents ran in parallel.
  - The Election-Results agent finished in 24 min; its verification found #44's precinct group misnamed.
  - The Cast-Vote-Records agent hit the 5-hour usage limit about 25 min in and sat idle about 9 h until the maintainer typed "Resume". It then finished in 13 min, and added exceptions anticipating #47's recount change.
  - #47, then #35, merged.
- **Friction:**
  - 4 stop-hook firings:
    - 2 false "unpushed" alarms from stale local branches;
    - 1 from `docs/variables.*` written during a copy-based run;
    - 1 from in-progress doc edits.
  - 2 `pkill -f` self-kills (exit 144), one of which aborted a chained background task.
  - Two edit slips were caught before commit, by tests and by a grep for a placeholder. One was a Python string replace that put a field inside the wrong parentheses; the other was a `CONTEST_BALLOTS` placeholder.

## 5. Gap analysis (Q3)

### 5.1 A delegated agent stalled on the usage limit, again, and resumed only when the maintainer asked (cost: about 9 h; one human prompt)

- **Observation:**
  - **Last sprint:** the Cast-Vote-Records fixer stalled 7 h on an HTTP 429 limit.
  - **This sprint:** the next Cast-Vote-Records fixer stalled from about 04:24 to 13:43 UTC. The task notification gave the reset time, 07:20.
  - **Resume:** nothing was scheduled at the reset. The work resumed only when the maintainer typed "Resume", more than six hours after the limit lifted.
  - **Unpushed work:** the agent's brief didn't ask it to push at milestones. Its partial work sat unpushed in the container all that time.
- **Root cause: missing.** Neither the briefs nor any definition says what to do when a subagent fails on a usage limit. The harness gives the reset time and the means to act on it (`send_later`, `SendMessage`). Nothing connects the two.
- **Why it matters:** this has recurred in both sprints that used long-running subagents. Each time the cost was hours of wall-clock time and a human prompt. A container can also be reclaimed while idle, and anything unpushed is then lost.

### 5.2 Stale local branches after auto-delete set off false stop-hook alarms (2 alarms, 1 hand-built lease)

- **Observation:**
  - **What happens:** after a PR merges, auto-delete removes the remote branch (P2-1), but the local branch keeps its old upstream. The stop hook then reports "12 unpushed commits" (10-26) or "1 unpushed commit" (11-10) for commits already on `main`.
  - **What it costs:** each alarm took a turn to diagnose.
  - **A related case:** the Election-Results agent had to build a lease expecting the branch to be absent.
- **Root cause: re-diagnosed.** The previous AAR traced this to single-branch clones and proposed fetching every branch, and the maintainer declined. The remaining cost is narrower: no step resets the session branch after a merge.
- **Why it matters:** the alarms are cheap one at a time, but they come back on every PR cycle.

### 5.3 `audit` writes `docs/variables.*` into the repo even when `CVR_DATA_DIR` points at a copy (1 alarm)

- **Observation:**
  - **What happened:** during the 10-30 rebuild, the run wrote only to the copy, but `audit` regenerated `docs/variables.{md,csv}` in the working tree.
  - **Why:** `DOCS_DIR` is not under the data directory.
  - **What it cost:** the stop hook asked for a commit mid-run.
- **Root cause: buried.** The Layout table says `audit` writes `docs/variables.*`, but the "Long runs" section doesn't say this file escapes the override.
- **Why it matters:** this is small, but it is exactly the half-finished-state commit that P0-1 exists to prevent.

### 5.4 `pkill -f <pattern>` killed its own shell (2 this sprint, 1 last)

- **Observation:**
  - **What happened:** `pkill -f "scripts.pipeline"` matched the bash process running the command, because the pattern appears in that process's own command line. The command exited with code 144.
  - **This sprint:** on 10-30 it aborted the chained "pipeline → notebook" background task, and the run had to be rebuilt as a fresh chain.
  - **Last sprint:** the previous AAR recorded one occurrence as a one-off (§5.6). With two more, it is a pattern.
- **Root cause: missing.** No definition says how to stop a background job. The harness's own task-stop tool, or a bracketed pattern (`pkill -f "[s]cripts.pipeline"`), avoids the self-match.

### 5.5 Drafted issues contained inaccuracies; verification caught them (strength, no change)

The maintainer's drafted issues had two errors:
- **#33 overstated a gap:** `reconcile --sov` already compared aggregates, though only informationally.
- **#44 named the wrong duplicate precinct group:** `201,202` instead of `202,500`.

Both were caught before anything was built on them. The spot-check before filing caught #33. The Election-Results agent caught #44 while checking its expected totals against the raw data. This is P2-3 working as intended; see §7.

### 5.6 One-offs (no change)

- **GitHub image cache:** a cached view on GitHub showed the old figure. The bytes on GitHub were correct; the fix was a hard refresh.
- **Two edit slips caught before commit:** a regex replace in the wrong place (tests failed), and a placeholder string (caught by grep). The existing checks did their job.

## 6. Recommended revisions (Q4)

### [P0-1] Add a "Working in a cloud session" section to each `AGENTS.md`

- **Target:** `AGENTS.md` in Election-Results, Cast-Vote-Records and City-Council-Minutes. It goes in the repos because a user-level `CLAUDE.md` doesn't persist in cloud containers. If the maintainer keeps one on their own machine, the same text belongs there.
- **Root cause:** missing (§5.1, §5.2, §5.4).
- **Medium:** definition text. These are judgment rules about sessions and delegation; a hook can't see subagent state.
- **Supersedes:** 2026-10-26 P1-1 (fetch every branch), which was declined.
- **Evidence:**
  - a usage-limit stall of about 9 h with a human "Resume", after 7 h last sprint;
  - 2 false "unpushed" stop-hook alarms;
  - 2 `pkill` self-kills this sprint, 3 in total.
- **Change:** add this to each `AGENTS.md`:
  > ## Working in a cloud session
  > - **Delegated agents: push at milestones.** A brief for a subagent should say "commit and push after each milestone", so its work survives an interruption.
  > - **Usage limits.** If a subagent stops on a usage limit, the notification gives the reset time. Schedule a check-in at that time (`send_later`), and resume the agent with `SendMessage` then, instead of waiting for someone to notice.
  > - **Stopping background jobs.** Stop a background task with the task-stop tool and its task ID. If you must match by name, bracket the first letter (`pkill -f "[s]cripts.pipeline"`) so the pattern doesn't match its own shell.
  > - **After a PR merges.** The branch is auto-deleted on GitHub. Reset the session branch: `git fetch origin main && git checkout -B claude/<branch> origin/main`, and drop the stale upstream with `git branch --unset-upstream`. Otherwise the stop hook reports commits that are already on `main`.
- **Why it works:** each item turns a recovery that happened in this sprint into the first step:
  - the resume at the reset time;
  - the bracketed pattern;
  - the post-merge reset.
  
  The push-at-milestones rule also limits what an interrupted agent can lose.
- **Owner:** auto-applyable (documentation only).
- **Status:** Proposed

### [P1-1] Say in "Long runs" that `audit` writes `docs/variables.*` into the repo

- **Target:** Cast-Vote-Records `AGENTS.md` → "Long runs".
- **Root cause:** buried (§5.3).
- **Medium:** definition text. The profile belongs in the repo, so moving it under the override would be wrong.
- **Evidence:** 1 stop-hook alarm mid-run, on 10-30.
- **Change:** append to the "Long runs" section:
  > `audit` also rewrites `docs/variables.{md,csv}` in the working tree (it documents the dataset, so it is not under `CVR_DATA_DIR`). Commit it together with the data you copy back, not on its own mid-run.
- **Owner:** auto-applyable.
- **Status:** Proposed

### [P2-1] Remove the stale Louisville exceptions in Cast-Vote-Records

- **Target:** `data/lookups/sov-exceptions.csv` (2 rows).
- **Root cause:** a known follow-up from #35. Election-Results #47 fixed the double count upstream, and reconcile now reports the rows as stale.
- **Medium:** data file.
- **Change:** delete the two 2023 Louisville Ward 2 rows. Reconcile should then report no stale exceptions.
- **Owner:** auto-applyable.
- **Status:** Proposed

### [P2-2] Delete the four merged Election-Results stack branches

- **Target:** GitHub (Election-Results): the `claude/gracious-babbage-b48zcc-{accuracy,pipeline,docs,unify}` branches.
- **Root cause:** they predate the auto-delete setting, and this session can't delete branches (403).
- **Medium:** one-time manual cleanup.
- **Change:** delete them in the web interface. Each is fully merged into `main`.
- **Owner:** maintainer.
- **Status:** Proposed

## 7. Strengths to sustain

- **"Checks by change type" (P0-2).** It turned verification from "the most expensive check available" into "the cheapest check that can catch this mistake":
  - the figure-only change re-rendered in about a minute, from the saved outputs;
  - the primaries with no City contests got a smoke test;
  - adding elections got the one full run.
  
  No ETA questions this sprint. Keep the table current when run times change.
- **Copy-based long runs (P0-1)** kept `main` clean through four multi-minute rebuilds. They also let late facts (records-request dates) go in through targeted re-cleans instead of restarts.
- **Batching design decisions before delegating.** Three forks were put to the maintainer in one question set before either agent started: the Presidential Primary key, whether the SoV check fails, and correcting Louisville. Neither agent needed steering mid-run.
- **Verification before building.** Spot-checking the drafted issues, and the agents checking expected numbers against raw data, caught both errors in the drafts. Independent recounts again matched exactly:
  - 2017/2018 voters and aggregates;
  - the 157 back-first merges;
  - the 2024 full SoV totals;
  - the new primaries.
- **Cross-repo coordination.** When Election-Results #47 opened, the Cast-Vote-Records agent was told about its branch and tested its new failing check against both versions of Election-Results. On its own, it added exceptions for the 2023 council recount that #47 would otherwise have broken.
- **The last AAR's mechanical fixes held:** `ruff format` (0 failures), auto-delete for new merges, and the failing SoV check.

## 8. Revision actions — tracking table

| ID | Pri | Target | Medium | Change | Owner | Status | Check next time |
|---|---|---|---|---|---|---|---|
| P0-1 | P0 | `AGENTS.md` × 3, "Working in a cloud session" | definition text | Push at milestones; resume limit-stalled agents at the reset time; stop jobs by task ID or a bracketed pattern; reset the branch after merge | auto | Proposed | Hours a subagent sat idle after its limit reset: ~6+ → 0. Human "Resume" prompts: 1 → 0. False "unpushed" stop-hook alarms: 2 → 0. `pkill` self-kills: 2 → 0 |
| P1-1 | P1 | Cast-Vote-Records `AGENTS.md` → "Long runs" | definition text | `audit` writes `docs/variables.*` into the repo | auto | Proposed | Stop-hook alarms caused by `docs/variables.*` during runs: 1 → 0 |
| P2-1 | P2 | Cast-Vote-Records `data/lookups/sov-exceptions.csv` | data file | Drop the 2 stale Louisville rows | auto | Proposed | Stale exceptions reported by `reconcile --sov`: 2 → 0 |
| P2-2 | P2 | Election-Results branches (GitHub) | manual cleanup | Delete the 4 merged stack branches | maintainer | Proposed | Merged `claude/*` branches on GitHub: 4 → 0 |
| (2026-10-26 P0-1, P1-2, P2-3 skill parts; earlier AAR's skill edits) | — | data-liberation skill | skill body | Paste-ready text already handed over | maintainer | Proposed | Applied in the skill: 0 of 7 → 7 of 7 |
