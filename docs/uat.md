# User acceptance test: SupplyTrace

Date of test: ____________  Facilitator: ____________

## Who to test with

Three to five people, none of whom have seen SupplyTrace.

- At least one non-technical person (for example a relative or friend who does not code).
- At least one person who has worked with invoices, accounts or finance, if you can find one.
- At least one developer or recruiter-type reader who would open a portfolio link.
- Do not coach them. Say only: "Please think aloud. I am testing the app, not you."

## Setup

- **Live demo:** https://supplytrace-fkpq.onrender.com (free hosting; the first load can take about a minute).
- **Before each tester:** open the link yourself once to wake the server. Note whether it was asleep and how long it took.
- **Local alternative:** run the README steps, then open http://127.0.0.1:8000.
  ```bash
  python -m venv .venv
  .venv\Scripts\activate
  pip install -r requirements.txt
  python -m src.api.server
  ```
- **Warning for testers:** the app is a shared demo on synthetic data. Reviews, vendor notes and the audit log are shared and reset on restart. Run testers one at a time and tell them not to upload real invoices.
- **Have ready:** one real-looking XML invoice file on the desk (a file from `data/raw_xml/` locally) for T3 only. Do not mention it earlier.
- **Record:** a stopwatch for each task, and a note of anything the tester says aloud, hesitates over or clicks that does nothing.

## Tasks

Read each goal aloud. Give no hints about where to click. Stop a task after 3 minutes and mark it fail.

**T1. Understand the product.** "You have never heard of this site. Tell me in your own words what it does and who it is for."
- Pass: tester says it checks supplier invoice files for problems, within 60 seconds of the page loading, without opening the About page.

**T2. See a failed invoice.** "You do not have an invoice file. Find out what the site says when an invoice has a problem."
- Pass: tester reaches a result with a failed status without being told about the samples, and can say which line or field the problem is in.

**T3. Check your own file.** "Here is an invoice file on this computer. Find out whether it is acceptable."
- Pass: tester uploads the file, sees a verdict, and states the verdict correctly (VALID, INVALID or needs review).

**T4. Understand the risk score.** "The result shows a risk number. Tell me what it means and what you would do next."
- Pass: tester says it is an experimental estimate, not a certain or measured chance, and names a sensible next step (fix the line, send to review, or no action). Fail if they treat it as a probability of fraud or say they do not know what to do.

**T5. Handle a bad file and a duplicate.** "Find out what happens if the same invoice is submitted twice, and what happens if you give the site a file that is not an invoice (for example a .txt file)."
- Pass: tester sees a duplicate flag or review entry for the repeat, and reads an error for the wrong file type that tells them what to do. Fail if they cannot find either result or say the message left them stuck.

## Post-test questions

Ask these in order, after the tasks.

1. What was the most confusing moment, and what did you expect to happen?
2. Would you trust the risk score? What would make you trust it more?
3. Would you send this link to someone, or mention it in an interview? What would you change first?

## Results

| Tester | T1 | T2 | T3 | T4 | T5 | Total time | Notes (waits, confusion, errors) |
|:--|:--|:--|:--|:--|:--|:--|:--|
|  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |

Write pass or fail in each T column. Record the wake-up time separately for each tester.

**Passing the UAT:** at least 4 of 5 testers pass T1, T2 and T3. T4 and T5 are expected to expose issues: list every failure in the notes column.

## Sign-off

Tested by: ____________  Date: ____________  Result (pass / pass with issues / fail): ____________  Signed: ____________

## Automated acceptance check (2026-11-09)

> Automated stand-in, not a real-user test: a scripted browser ran each task on the live demo. It shows each task *can* be completed, not that people understand the page. The real-user results table above is still to be filled.

Run against https://supplytrace-fkpq.onrender.com with Chrome driven by Playwright, at 390x844 and 1280x800. The server was already awake (first load under 1 s). Eight analyses per size or fewer: one sample ("Missing ID"), the same XML file from `data/raw_xml/` twice (`invoice_0001.xml` on phone, `invoice_0002.xml` on desktop), and one `.txt` file. The files were new to the audit log, so the demo's audit log and review queue gained two entries per size; no review was assigned, approved or rejected.

| Task | phone 390px | desktop 1280px | notes |
|:--|:--|:--|:--|
| T1 Understand the product | pass (wording only) | pass (wording only) | The first screen's heading reads "Catch invalid, duplicate and risky supplier invoices before they're paid." with a line on the five rules and the verdict labels. Whether a person says it in their own words within 60 s: n/a (needs a person). |
| T2 See a failed invoice | pass | pass | The "Missing ID" chip gives INVALID, "1 rule failed", with the failing rule marked on a line. The chips were in the first screen, so "without being told about the samples" is n/a (needs a person). |
| T3 Check your own file | pass | pass | Upload gave VALID in about 8 s. Stating the verdict correctly: n/a (needs a person). The native file picker did not open under automation in 3 of 3 attempts per size (clicking "Select file"), so the file was set on the hidden input directly. Code reads correctly (`browse-btn` calls `input.click()`), so this is probably a harness quirk, but not confirmed. |
| T4 Understand the risk score | pass (labels only) | pass (labels only) | The "Experimental" tag sits beside the score, the "not a calibrated probability" note and a "Next step" line are present. Whether a person reads it as an estimate: n/a (needs a person). |
| T5 Bad file and duplicate | pass | pass | Re-uploading the same file showed "Exact duplicate of invoice #NNN ... Find it in the audit log". A `.txt` file showed the red message "notinvoice.txt: Only .xml files are supported." Whether that message tells a person what to do: n/a (needs a person). |

### Accessibility summary (axe-core 4.10.2)

Views scanned at both sizes: check/home, a result (after "Missing ID"), review, vendors, about, rules (6 views x 2 sizes). Not scanned: batch, audit log. Totals across the 12 scans: critical 0, serious 3 findings (2 distinct rule IDs), moderate 2 findings (1 rule ID), minor 0.

- `color-contrast` (serious): 37 nodes on the result view at both sizes, the XML line numbers (`.xml-ln`, marked `aria-hidden`) are below the contrast ratio.
- `scrollable-region-focusable` (serious): 5 nodes on the rules view at 390px only, the `<pre>` rule examples scroll but cannot be reached by keyboard.
- `landmark-unique` (moderate): review and vendors views at both sizes, two landmarks share the same name or role (the view `<section>` is the flagged element).
- The check/home and about views had no violations. Automated checks cover only part of accessibility; keyboard and screen-reader use are not tested here.
- Fixed the same day: XML line-number and punctuation contrast, the focusable example blocks on Rules, and unique Review and Vendors landmark names. A re-scan at 390 and 1280 px in both themes found no violations on check (with a result), rules, review, vendors and about.

### Bugs found

None in task behaviour. Observations, not defects: after the `.txt` error the previous result stays on screen below it (phone screenshot T5-phone.png), which may look like the `.txt` file was accepted; the `.txt` message states the rule but not the next step; the three axe rule IDs above are real, small accessibility fixes.

- Fixed the same day: a rejected upload now hides the previous result and the error adds a next step (use a sample or download one); a sample download link was added beside the upload box. Verified by reproducing before (result stayed visible) and after (result hidden).

Screenshots and raw results: `C:\Users\jayan\AppData\Local\Temp\claude\4058a2d8ff66180b\990022ee-5eea-4ecd-9062-80f21cc23e98\scratchpad\uat-supplytrace\` (not in the repo).
