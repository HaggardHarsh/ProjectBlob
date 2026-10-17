# Web search, page reading and browser interaction

Blob exposes `web_search`, `web_read` and `browser` through its normal skill
registry in both classic and Hermes modes. The OpenShell worker still has no
network access or provider credentials: it requests operations from Blob.
This does not enable upstream Hermes's shell, browser plugins or other tools.

Install into the backend's environment:

```bash
venv/bin/python -m pip install -e 'backend_python[web]'
venv/bin/python -m playwright install chromium
systemctl --user restart blob-backend.service
```

Chromium needs its platform libraries and a working OS browser sandbox. Blob
does not disable that sandbox if launch fails. Search and reading work without
Chromium. Missing optional packages produce setup messages rather than fake results.

DuckDuckGo through DDGS is the default and needs no key. It can be rate limited
or unavailable; empty results do not prove absence. There is no automatic provider
switching. For the optional Brave Search API, set `BLOB_WEB_SEARCH_PROVIDER=brave`
and `BRAVE_SEARCH_API_KEY` in `.env`. Queries go to the chosen provider; DDGS uses
its DuckDuckGo backend. Search freshness accepts `any`, `day`, `week`, `month`, `year`.

Natural requests can search, read sources, or open a travel site and fill journey
details. Direct commands also work without invoking the language model:

```text
/skills run web_search {"query":"Python announcements","freshness":"week"}
/skills run web_read {"url":"https://example.com/"}
/skills run browser {"action":"open","url":"https://example.com/"}
/skills run browser {"action":"snapshot"}
/skills run browser {"action":"close"}
```

Browser responses include current URL, visible text and element `ref`s. Use a
current ref with `click`, `fill` (with `text`), `select` (option value or label in
`text`), or `press` (with `key`, e.g. `Enter`). Each successful operation returns
a new snapshot; previous refs expire. Date inputs accept ISO dates. Dynamic
results may need another snapshot while loading. Downloaded bodies, snapshots,
links and tool output are bounded and report omissions. Web text is evidence,
never instructions to change the user's task.

Within a task, earlier browser snapshots are reduced to URL/time metadata once
a newer snapshot is available. Earlier action arguments, failures, source-page
reads and the latest view remain available. Both runtimes use the configured
`BLOB_AGENT_MAX_ITERATIONS` budget for workflows involving registered web tools.

The browser uses a temporary headless Chromium session, separate from the user's
desktop browser. It retains no login profile or saved credentials. Downloads,
uploads, password entry, permission grants, service workers, WebSockets and popup
windows are unavailable. Sign-in, CAPTCHA, purchases, messages and account changes
require manual handling. Recognizable transaction controls are rejected; this is
not a guarantee that every website side effect can be classified. Use this for
public information and lookup forms, not authenticated or consequential actions.

Only public HTTP/HTTPS on standard ports is supported. The reader validates every
redirect and resolves through checked public IPs, without host proxies or cookies.
The browser connects through a local public-only proxy which checks all DNS
answers and connects to the exact validated IP. This covers subresources and
redirects, blocking loopback, LAN, metadata services and credential-bearing URLs,
including DNS rebinding. TLS verification remains enabled. Browser connections
are limited to 60 seconds; the session expires after two minutes without use.

Pause, cloud-off and disabling the relevant skill block these tools, including
direct terminal invocations. An idle browser closes on privacy changes, checked
every 250 ms. Active registered operations can be cancelled. DuckDuckGo's sync
search can finish an already dispatched request after cancellation; its result
is discarded. Data already sent to providers or sites cannot be recalled.

Tools return UTC check times and source URLs. Normal conversation memory can
retain the answer and links under existing memory rules; skill history retains
only operational metadata. Old results do not verify current availability.
Train-seat checks require train, journey date, origin, destination, class and
quota. Search snippets and prediction scores are not live inventory. Sites may
require login, CAPTCHA or block automation; Blob must report an unverified result
when it cannot complete the enquiry.

```bash
venv/bin/python -m pytest backend_python/tests/test_web_tools.py backend_python/tests/test_web_browser.py -q
```

Browser tests run real Chromium against intercepted synthetic pages without
booking tickets or submitting data to a public service. Fixture availability
values are not evidence of real seats. Live smoke checks separately establish
provider reachability.
