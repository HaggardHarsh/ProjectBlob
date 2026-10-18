# Tool and retrieval security review

Reviewed locally on 2026-10-18. This is an implementation review with regression
fixtures, not an independent penetration test or a universal injection guarantee.

## Trust boundaries and tested controls

| Input or boundary | Enforcement | Regression evidence |
| --- | --- | --- |
| Retrieved instructions request shell/reminder actions | Current user intent determines model tool permissions outside the model; both classic and native Hermes tool dispatch enforce them. | `test_tool_policy.py`, existing live-grounding and Hermes tool tests. |
| Private recalled text appears in a model-generated search query | Host replaces model query with the public request-derived query before execution. | Injection fixture tries to transmit a synthetic bank code; observed outbound query excludes it. |
| Invented URL or form value contains private context | Opens require a user/tool-observed public URL; fill/select values must occur in public user input. | Unobserved URLs and private form values are rejected before execution. |
| Shell permission is reused for an unrelated command | Exact user command or fixed request-matching diagnostic required, then existing namespace/command policy still applies. | Unauthorized command rejection and approved-folder/sandbox tests. |
| A harmless-looking browser control submits a mutation | Browser routing rejects every method except GET/HEAD, independently of labels. Public-only proxy validates addresses and redirects; Chromium sandbox stays enabled. | Real Chromium fixture blocks POST before proxy access; DNS/redirect/private-address fixtures remain active. |
| Search snippets or model-invented sources support a live answer | Actual nonempty page read plus checked citation required before display/storage; live streaming waits for verification. | Generic current-info and product fixtures, both runtimes; snippets alone fail. |
| A terminal escape or configured provider key reaches output | Control-sequence normalization and known-key redaction; streamed output withholds enough trailing characters for whole-key filtering. | ANSI/OSC and split-secret fixtures. |
| Updates admit writes before health commit | Maintenance marker blocks chat/config/skill writes and reminder acknowledgements; workers pause reminder delivery. | Authenticated IPC maintenance fixture and stopped-store recovery tests. |

Model authority uses current public input and bounded previous public lookup
metadata. Privacy reset clears that metadata. A same-turn page-read cache avoids
repeated preflight/model reads; a new user turn must fetch fresh evidence.
Direct `/skills run` is explicit user authority, with normal privacy, command and
network checks. Installing a local skill is trusted code installation.

## Residual risks and scope

- A citation is necessary for a live response but does not prove semantic accuracy
  or source authority. Test sources are synthetic; live grounding quality needs
  repeated provider/site evaluations.
- Public GET endpoints may have side effects. Browser isolation and method checks
  are not a complete transaction classifier. Login, CAPTCHA, purchases and account
  changes remain manual, and POST enquiry sites cannot be automated here.
- No validated train inventory adapter exists. Generic page words and numbers do
  not bind train, date, route, class, quota and check time, so Blob returns a source
  for manual verification rather than certifying seats.
- Known-key filtering is not general PII detection or arbitrary-secret detection.
  Users can explicitly submit private text; normal opted-in inference still sends
  recalled context and selected document content to the configured provider.
- Explicitly requested installed custom tools retain their declared behavior;
  these controls do not audit arbitrary locally installed code.
- Nested Bubblewrap cannot mount `/proc` in the disposable rootless Ubuntu
  container. Its actual isolation test is skipped there, with unsupported execution
  remaining fail-closed. The host suite exercises the supported namespace path.
- Review heuristic request classification, user-authorized public input, encoded
  exfiltration, deceptive links and long-running cancellation independently before
  a broader release. This review does not certify all adversarial inputs.

See [privacy model](../privacy_model.md), [web tools](../web_tools.md) and
[launch evidence](launch_criticals.md).
