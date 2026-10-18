"""Explicit local commands, processed before the conversation lock."""

import json
import shlex


DATA_SHARING_NOTICE = """Blob stores conversation memory, selected document copies, generated answers, reminders and enrolled face samples locally. Local stores are not encrypted by Blob.
Cloud assistance sends your messages, relevant recalled memories, selected document text/images and tool results to the configured AI provider (Nebius by default). Web searches send queries to the search provider; page reading and browser lookups contact the selected websites.
Automatic screen shielding blocks screen capture and some storage; it does not turn off cloud chat. /privacy pause blocks new cloud requests, capture, camera and memory writes. Local reminders continue. /privacy cloud off blocks cloud assistance and web tools.
Automatic screen awareness is off until /awareness on. Camera access occurs only on request. Enabling cloud assistance also permits background memory consolidation of eligible user statements.
Use /memory, /files saved, /results, /reminders and /camera list to inspect each store; their deletion commands are separate. Data already sent to providers cannot be recalled by Blob.
New installations start with cloud assistance off. Use /privacy cloud on to enable it after reviewing this notice, or leave it off for local commands."""

PRIVACY_HELP = """/privacy status | explain | pause | resume | cloud on|off
/privacy folders | allow /path/to/folder | revoke /path/to/folder
/privacy disable <skill> | enable <skill>
Privacy pause blocks cloud requests, capture, camera and new memory writes.
Local reminders continue. Cloud mode sends messages and selected context to Nebius."""
MEMORY_HELP = """/memory [episodic|middle|semantic]
/memory show <tier> <id>
/memory forget <tier> <id> | /memory forget all
Forgetting a fact also deletes source episodes containing that quote and their derived facts, preventing recovery on restart.
Saved documents, generated results, reminders and enrolled faces have separate deletion commands."""


async def handle_control_command(orchestrator, command):
    controls = orchestrator.controls
    try:
        parts = shlex.split(command)
        verb = parts[1].lower() if len(parts) > 1 else "status"
        if parts[0].lower() == "/privacy":
            if verb == "explain" and len(parts) == 2:
                return DATA_SHARING_NOTICE
            if verb in {"status", "folders"} and len(parts) <= 2:
                return json.dumps(controls.state, indent=2)
            if verb in {"pause", "resume"} and len(parts) == 2:
                controls.update(paused=verb == "pause")
                if controls.paused:
                    controls.cancel_requests()
                    orchestrator.clear_private_context()
                shield = orchestrator.screen_sampler.privacy_shield
                shield.is_active = False
                active = shield.is_capture_blocked()
                await shield._broadcast_state(active, "Privacy pause" if controls.paused else "Privacy controls updated")
                return "Privacy paused. Local reminders continue." if controls.paused else "Privacy resumed."
            if verb == "cloud" and len(parts) == 3 and parts[2] in {"on", "off"}:
                controls.update(cloud_enabled=parts[2] == "on")
                if not controls.cloud_enabled:
                    controls.cancel_requests()
                shield = getattr(getattr(orchestrator, "screen_sampler", None), "privacy_shield", None)
                if shield:
                    await shield._broadcast_state(shield.is_capture_blocked(), "Cloud settings updated")
                return ("Cloud assistance on. Messages, relevant memories, selected content and tool results may now go to your AI provider. Web tools contact search providers and websites. Background memory consolidation is enabled. Use /privacy explain for details or /privacy cloud off to stop new requests."
                        if controls.cloud_enabled else "Cloud assistance off.")
            if verb == "allow" and len(parts) == 3:
                return f"Approved read-only folder: {controls.approve(parts[2])}"
            if verb == "revoke" and len(parts) == 3:
                from pathlib import Path
                folder = str(Path(parts[2]).expanduser().resolve())
                controls.update(approved_folders=[path for path in controls.state["approved_folders"] if path != folder])
                controls.cancel_requests()
                return f"Revoked folder: {folder}"
            if verb in {"enable", "disable"} and len(parts) == 3:
                if not orchestrator.skill_registry.get_skill(parts[2]):
                    raise ValueError("Unknown skill. Use /skills to list names.")
                disabled = set(controls.state["disabled_skills"])
                if verb == "disable":
                    disabled.add(parts[2])
                else:
                    disabled.discard(parts[2])
                controls.update(disabled_skills=sorted(disabled))
                controls.cancel_requests()
                return f"{parts[2]}: {verb}d."
            return PRIVACY_HELP
        store = orchestrator.vector_store
        if verb == "forget":
            if parts[2:] == ["all"]:
                controls.cancel_requests()
                with controls.lock:
                    controls.generation += 1
                    count = store.forget_personal_memory()
            elif len(parts) == 4 and parts[2] in {"episodic", "middle", "semantic"}:
                controls.cancel_requests()
                with controls.lock:
                    controls.generation += 1
                    count = store.forget_personal_memory(parts[2], parts[3])
            else:
                return MEMORY_HELP
            orchestrator.clear_private_context()
            return f"Deleted {count} personal memory record(s), including linked source/derived records."
        if verb == "show" and len(parts) == 4 and parts[2] in {"episodic", "middle", "semantic"}:
            data = store._collection(parts[2]).get(ids=[parts[3]], include=["documents"])
            return data["documents"][0] if data["ids"] else "No memory with that ID."
        if len(parts) <= 2 and (len(parts) == 1 or verb in {"episodic", "middle", "semantic"}):
            tiers = [verb] if len(parts) == 2 else ["middle", "semantic", "episodic"]
            rows = []
            for tier in tiers:
                data = store._collection(tier).get(limit=50, include=["documents"])
                rows.extend(f"{tier} {item_id}: {text[:300]}" for item_id, text in zip(data["ids"], data["documents"]))
            return ("\n".join(rows) or "No personal memories stored.") + "\nUp to 50 records per tier.\n" + MEMORY_HELP
        return MEMORY_HELP
    except (ValueError, OSError) as exc:
        return str(exc)
