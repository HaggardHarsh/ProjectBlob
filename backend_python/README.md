# Blob backend

Python backend for Project Blob's Linux desktop companion. The complete setup and
feature documentation is in the repository's root README.

Install with `pip install .` for the backend, or `pip install '.[dev,web,vision]'`
for the release-test profile. New installations start with cloud assistance and
automatic screen awareness off. Run `blob-backend --daemon` and connect using
`blob-chat`. Read `/privacy explain` before enabling cloud assistance with
`/privacy cloud on`. Cloud use requires a private `NEBIUS_API_KEY` configuration.

Occasional conversation invitations are separately opt-in with `/proactive on`.
They require a compatible visible overlay and cloud assistance; `/proactive quiet`
pauses them for today and `/proactive off` disables them across restarts.

The published backend package does not contain the C++ overlay, the GNOME
extension, Hermes, or the OpenShell runtime. Those have separate setup steps.
