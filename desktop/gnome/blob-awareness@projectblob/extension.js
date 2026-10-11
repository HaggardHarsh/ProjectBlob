import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const IFACE = `<node><interface name="org.projectblob.Awareness">
<method name="GetWindow"><arg type="s" direction="out"/></method>
<method name="Capture"><arg type="s" direction="in"/>
<arg type="s" direction="in"/>
<arg type="s" direction="out"/><arg type="ay" direction="out"/></method>
</interface></node>`;

// The native screenshot implementation accepts a memory stream on GNOME 45+.
Gio._promisify(Shell.Screenshot.prototype, 'screenshot_window');

export default class BlobAwareness extends Extension {
    enable() {
        this._enabled = true;
        this._busy = false;
        this._epoch = 0;
        this._focusSignal = global.display.connect('notify::focus-window', () => this._epoch++);
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._dbus.export(Gio.DBus.session, '/org/projectblob/Awareness');
    }

    disable() {
        this._enabled = false;
        this._epoch++;
        this._dbus?.unexport();
        this._dbus = null;
        if (this._focusSignal)
            global.display.disconnect(this._focusSignal);
        this._focusSignal = null;
    }

    _state() {
        const window = global.display.focus_window;
        if (!this._enabled || Main.sessionMode.isLocked || Main.screenShield.locked ||
            Main.overview.visible || !window || window.minimized)
            return {blocked: true};
        const actor = window.get_compositor_private();
        if (!actor || !actor.visible)
            return {blocked: true};
        const rect = window.get_frame_rect();
        return {
            blocked: false,
            id: `${window.get_stable_sequence()}:${this._epoch}:${window.get_title() ?? ''}`,
            title: window.get_title() ?? '',
            process_name: window.get_wm_class() ?? '',
            pid: window.get_pid(),
            bbox: [rect.x, rect.y, rect.x + rect.width, rect.y + rect.height],
        };
    }

    GetWindow() {
        return JSON.stringify(this._state());
    }

    _authorized(token) {
        try {
            const file = Gio.File.new_for_path(`${GLib.get_user_runtime_dir()}/blob-awareness/token`);
            const info = file.query_info('standard::type,unix::mode,unix::uid',
                Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null);
            if (info.get_file_type() !== Gio.FileType.REGULAR ||
                (info.get_attribute_uint32('unix::mode') & 0o077) !== 0 ||
                info.get_attribute_uint32('unix::uid') !== new Gio.Credentials().get_unix_user())
                return false;
            const [ok, bytes] = file.load_contents(null);
            const expected = new TextDecoder().decode(bytes).trim();
            return ok && /^[a-f0-9]{64}$/.test(expected) && token === expected;
        } catch {
            return false;
        }
    }

    async CaptureAsync([expected, token], invocation) {
        const state = this._state();
        const reject = () => invocation.return_value(new GLib.Variant('(say)', ['{"blocked":true}', []]));
        if (!this._authorized(token) || state.blocked || state.id !== expected || this._busy) {
            reject();
            return;
        }
        this._busy = true;
        const stream = Gio.MemoryOutputStream.new_resizable();
        try {
            await new Shell.Screenshot().screenshot_window(false, false, stream);
            stream.close(null);
            const after = this._state();
            if (after.blocked || after.id !== expected || stream.get_data_size() > 8 * 1024 * 1024) {
                reject();
                return;
            }
            const data = stream.steal_as_bytes().get_data();
            invocation.return_value(new GLib.Variant('(say)', [JSON.stringify(after), data]));
        } catch {
            reject();
        } finally {
            if (!stream.is_closed())
                stream.close(null);
            this._busy = false;
        }
    }
}
