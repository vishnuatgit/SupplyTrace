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

**Passing the UAT:** at least 4 of 5 testers pass T1, T2 and T3. T4 and T5 are expected to expose issues: list every failure in the notes column and add it to `docs/end-to-end-review.md` as evidence.

## Sign-off

Tested by: ____________  Date: ____________  Result (pass / pass with issues / fail): ____________  Signed: ____________
