# Contributor review before submission

The MIT license for this companion was selected by the user on 31 October 2026. It does not change LabRelay's licensing.

Before making the event's authorship/rights declaration, the contributor should review and be able to explain:

1. The separate read-only Function authenticates the caller JWT and derives organization scope from active membership.
2. Business records remain private; the setup key is not used by Kestra. The deployed Function uses only its per-execution `rows.read` scope.
3. Cursor pagination and before/after revision checks prevent incomplete or unstable exports from being reported clean. Orphan rows and direct administrator edits are outside the coverage guarantee.
4. An earlier missing receipt remains historically valid after later acceptance. Revision and acceptance evidence determine resolution.
5. Reports are saved before the failure gate, so a failed execution may still have valid diagnostic artifacts.
6. Tests, real Appwrite Process-runner runs, and the Docker CI runs have distinct verification boundaries.

Development used ChatGPT/Codex assistance. This document is a review aid, not evidence that the human review or organizer eligibility approval has occurred. The contributor must make personal declarations themselves; no automated step should check them on the contributor's behalf.
