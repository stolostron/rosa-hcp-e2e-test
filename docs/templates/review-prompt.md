# Code Review Prompt

Use this prompt for thorough line-by-line reviews:

```
Do a line-by-line review of [file/PR]. Read every line of every file 
involved - the full file, not just the diff. Check for:

- Bugs: logic errors, wrong comparisons, off-by-one, race conditions
- Security: secrets in logs, missing auth, injection risks
- Resilience: unhandled errors, missing fallbacks, silent failures
- Consistency: does it match patterns used elsewhere in this codebase
- Data flow: does every input get validated, every output get used
- Dead code: unused imports, unreachable branches, orphaned variables
- Edge cases: empty lists, None values, missing keys, timeout handling
- Linting: syntax errors, YAML/JSON validity, indentation, quoting
- Build/runtime: missing dependencies, import errors, broken references

For each issue found, report:
1. File and line number
2. Severity (bug / security / risk / lint / style)
3. What's wrong (with the actual code snippet)
4. How to fix it (with the corrected code)

Cross-reference: check if the same pattern exists elsewhere in the 
file/codebase and flag ALL instances, not just the first one.

Test impact: for each fix, identify which existing tests cover it 
and whether new tests are needed.

Regression: verify the changes don't break any existing behavior. 
Check callers of modified functions, templates that reference changed 
variables, and CI pipelines that depend on changed files.

Validate: run any available linters, type checkers, or test suites 
and report the results. If tests fail, include the failure output.

PR metadata: read the PR title and description carefully. After the 
code review, update them if they are inaccurate, incomplete, or don't 
reflect the current state of the changes. The description should 
include a clear summary of what changed, why, and a test plan.

After the review, give a confidence score out of 100 with specific 
line-number references for any deductions.
```
