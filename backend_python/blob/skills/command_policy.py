"""Shared policy for argument-vector commands; never invoke a shell."""

READ_COMMANDS = {"find", "grep", "ls", "cat", "head", "tail"}
FIND_ACTIONS = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprintf", "-fls"}


def allowed_command(argv, permissions):
    if not argv or not all(isinstance(value, str) and "\0" not in value for value in argv):
        return False
    executable = argv[0]
    if executable in READ_COMMANDS:
        return "filesystem.read" in permissions and not (executable == "find" and set(argv[1:]) & FIND_ACTIONS)
    if executable == "git":
        if "shell.execute" not in permissions or len(argv) < 2:
            return False
        # Output files and external diff/text conversion drivers can write or run code.
        if any(arg in {"-c", "-o", "--ext-diff", "--textconv", "--output"} or
               arg.startswith(("--output=", "--ext-diff=", "--textconv=", "--exec", "--show-signature")) or
               "%G" in arg for arg in argv[2:]):
            return False
        if argv[1] == "branch":
            # Bare branch names, -d, -D, -m, -M, -c, and -C modify the repository.
            flags = {"-a", "--all", "-r", "--remotes", "--list", "--show-current", "-v", "-vv", "--verbose", "--no-color"}
            return all(arg in flags or arg.startswith(("--sort=", "--format=")) for arg in argv[2:])
        return argv[1] in {"status", "log", "diff"} or argv[1:3] == ["stash", "list"]
    if executable == "curl":
        return ("network.http" in permissions and len(argv) in {2, 3}
                and argv[-1].startswith("https://") and
                all(arg in {"-s", "--silent"} for arg in argv[1:-1]))
    if executable in {"echo", "date", "df", "free", "uname"}:
        if executable == "date":
            # GNU date also accepts a bare numeric operand that sets the clock.
            takes_value = False
            for arg in argv[1:]:
                if takes_value:
                    takes_value = False
                    continue
                if arg in {"-d", "--date", "-r", "--reference"}:
                    takes_value = True
                elif arg not in {"-u", "--utc", "--universal", "-I", "--iso-8601", "-R", "--rfc-email"} and not arg.startswith(
                        ("+", "--date=", "--reference=", "--iso-8601=", "--rfc-3339=")):
                    return False
            if takes_value:
                return False
        return "shell.execute" in permissions
    return executable in {"python", "python3"} and argv[1:] == ["--version"] and "shell.execute" in permissions


def command_argv(argv):
    """Disable configured Git subprocess helpers and optional index writes."""
    if argv[0] != "git":
        if argv[0] == "curl":
            return ["curl", "--disable", "--proto", "=https", *argv[1:]]
        return argv
    prefix = ["git", "--no-pager", "--no-optional-locks", "-c", "core.fsmonitor=false"]
    options = ["--no-ext-diff", "--no-textconv"] if argv[1] in {"diff", "log"} else []
    return prefix + [argv[1], *options, *argv[2:]]
