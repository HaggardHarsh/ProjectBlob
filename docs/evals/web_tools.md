# Web tools verification

Verified on 2026-10-17 using the configured Nebius Nemotron Super model and the
real Hermes worker in OpenShell. All stores and requests were synthetic.

[Live results](web_tools.json) cover three workflows:

| Workflow | Observed tool actions | Outcome |
| --- | --- | --- |
| Find and read Python's official documentation | `web_search`, `web_read` | Source title and URL returned; 3 model calls |
| Open a public page | `browser` | example.com title and URL returned; 2 model calls |
| Fill and submit a synthetic availability form | Four `browser` operations | Date and Third AC selection submitted; fixture status AVAILABLE 7 reported; 5 model calls |

The first two used the public internet; the third used real Chromium with an
intercepted local fixture. It does not establish real train availability or
compatibility with IRCTC, login, CAPTCHA, or every travel website. Provider and
site failures remain possible. The form answer's status check normalizes Unicode
whitespace. Live run receipts confirm executed tools, rather than relying only
on claimed actions in assistant text.

Deterministic tests additionally exercise both agent routes, stale browser refs,
context compaction before budget checks, public-only DNS/redirects, credential
handling, bounded output, cancellation, and closing an idle browser on privacy
changes. The browser tests use real Chromium and synthetic page content. The
OpenShell image and its denied-network policy remain unchanged; web operations
execute through Blob's existing host tool bridge.

The complete backend regression suite passed **543 tests** with the web tools
installed, including real Chromium fixture tests and closing an idle HTTPS tunnel
without waiting for its timeout. A live navigation-and-close check also passed.
