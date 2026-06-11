import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, replace
from functools import lru_cache


@dataclass(frozen=True)
class ShellProfile:
    id: str
    label: str
    executable: str
    kind: str
    args: tuple = ()
    source: str = "path"


_WINDOWS_TERMINAL_SETTINGS = [
    os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "Packages",
        "Microsoft.WindowsTerminal_8wekyb3d8bbwe",
        "LocalState",
        "settings.json",
    ),
    os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "Packages",
        "Microsoft.WindowsTerminalPreview_8wekyb3d8bbwe",
        "LocalState",
        "settings.json",
    ),
]


def _norm(path):
    return os.path.normpath(os.path.expandvars(os.path.expanduser(path))) if path else ""


def _path_key(path):
    if not path:
        return ""
    return os.path.normcase(os.path.abspath(_norm(path)))


def _classify(path):
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    if stem in ("cmd", "command"):
        return "cmd"
    if stem in ("pwsh", "powershell"):
        return "powershell"
    if stem in ("bash", "sh", "zsh"):
        return "posix"
    if stem == "fish":
        return "fish"
    if stem == "wsl":
        return "wsl"
    if stem in ("nu", "nushell"):
        return "nushell"
    return "generic"


def _legacy_id(path):
    stem = os.path.splitext(os.path.basename(path))[0].lower()
    if stem in ("cmd", "pwsh", "powershell", "bash"):
        return stem
    if stem in ("wsl", "sh", "zsh", "fish", "nu"):
        return stem
    return f"path:{_norm(path)}"


def _friendly_name(path, fallback=None):
    stem = os.path.splitext(os.path.basename(path))[0]
    known = {
        "cmd": "Command Prompt",
        "pwsh": "PowerShell 7",
        "powershell": "Windows PowerShell",
        "bash": "Bash",
        "wsl": "WSL",
        "sh": "sh",
        "zsh": "zsh",
        "fish": "fish",
        "nu": "Nushell",
    }
    return fallback or known.get(stem.lower(), stem)


def _split_commandline(commandline):
    commandline = os.path.expandvars(commandline or "").strip()
    if not commandline:
        return []

    # Enough for Windows Terminal profile command lines: first token may be quoted.
    if commandline[0] in ("'", '"'):
        quote = commandline[0]
        end = commandline.find(quote, 1)
        if end > 0:
            first = commandline[1:end]
            rest = commandline[end + 1 :].strip()
            return [first] + rest.split()
    return commandline.split()


def _strip_json_comments(text):
    text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return text


def _candidate_names():
    if sys.platform == "win32":
        return [
            "pwsh",
            "powershell",
            "cmd",
            "bash",
            "wsl",
            "nu",
            "fish",
            "zsh",
            "sh",
        ]
    shell = os.environ.get("SHELL")
    names = ["bash", "zsh", "fish", "sh", "pwsh", "nu"]
    if shell:
        names.insert(0, shell)
    return names


def _common_windows_paths():
    if sys.platform != "win32":
        return []
    roots = [
        os.environ.get("ProgramFiles", ""),
        os.environ.get("ProgramFiles(x86)", ""),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    candidates = []
    for root in roots:
        if not root:
            continue
        candidates.extend(
            [
                os.path.join(root, "Git", "bin", "bash.exe"),
                os.path.join(root, "Git", "usr", "bin", "bash.exe"),
                os.path.join(root, "Programs", "Git", "bin", "bash.exe"),
                os.path.join(root, "Programs", "PowerShell", "7", "pwsh.exe"),
            ]
        )
    return candidates


def _windows_terminal_profiles():
    if sys.platform != "win32":
        return []

    profiles = []
    for settings_path in _WINDOWS_TERMINAL_SETTINGS:
        if not settings_path or not os.path.exists(settings_path):
            continue
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                data = json.loads(_strip_json_comments(f.read()))
        except Exception:
            continue

        for item in data.get("profiles", {}).get("list", []):
            commandline = item.get("commandline")
            parts = _split_commandline(commandline)
            if not parts:
                continue

            executable = _norm(parts[0])
            resolved = shutil.which(executable) or executable
            if not os.path.exists(resolved) and not shutil.which(resolved):
                continue

            profiles.append(
                ShellProfile(
                    id=f"wt:{item.get('guid', _path_key(resolved))}",
                    label=item.get("name") or _friendly_name(resolved),
                    executable=resolved,
                    kind=_classify(resolved),
                    args=tuple(parts[1:]),
                    source="windows-terminal",
                )
            )
    return profiles


def _make_profile(path, label=None, source="path", profile_id=None, args=()):
    resolved = shutil.which(path) or _norm(path)
    return ShellProfile(
        id=profile_id or _legacy_id(resolved),
        label=label or _friendly_name(resolved),
        executable=resolved,
        kind=_classify(resolved),
        args=tuple(args or ()),
        source=source,
    )


def _default_profile():
    if sys.platform == "win32":
        comspec = os.environ.get("COMSPEC") or shutil.which("cmd") or "cmd.exe"
        return _make_profile(comspec, label=f"Sistema predeterminado ({os.path.basename(comspec)})", profile_id="default")

    shell = os.environ.get("SHELL") or shutil.which("sh") or "/bin/sh"
    return _make_profile(shell, label=f"Sistema predeterminado ({os.path.basename(shell)})", profile_id="default")


def _dedupe_labels(profiles):
    counts = {}
    for profile in profiles:
        counts[profile.label] = counts.get(profile.label, 0) + 1

    result = []
    for profile in profiles:
        if counts.get(profile.label, 0) <= 1:
            result.append(profile)
        else:
            result.append(replace(profile, label=f"{profile.label} ({profile.executable})"))
    return result


@lru_cache(maxsize=1)
def detect_shell_profiles():
    profiles = []
    seen_paths = set()
    seen_ids = set()

    def add(profile):
        key = None if profile.source == "windows-terminal" else _path_key(profile.executable)
        if key and key in seen_paths:
            return
        if profile.id in seen_ids:
            return
        profiles.append(profile)
        if key:
            seen_paths.add(key)
        seen_ids.add(profile.id)

    for name in _candidate_names():
        path = shutil.which(name)
        if path:
            add(_make_profile(path))

    for path in _common_windows_paths():
        if os.path.exists(path):
            add(_make_profile(path, source="well-known"))

    for profile in _windows_terminal_profiles():
        add(profile)

    if not profiles:
        add(_default_profile())

    return tuple(_dedupe_labels(profiles))


def get_available_shells(include_default=False):
    profiles = list(detect_shell_profiles())
    if include_default:
        default = _default_profile()
        if not any(p.id == "default" for p in profiles):
            profiles.insert(0, default)
    return profiles


def get_default_shell_id():
    profiles = get_available_shells(include_default=False)
    if profiles:
        return profiles[0].id
    return "default"


def get_shell_profile(shell_id=None):
    shell_id = shell_id or get_default_shell_id()

    if shell_id == "default":
        return _default_profile()

    if isinstance(shell_id, str) and shell_id.startswith("path:"):
        return _make_profile(shell_id[5:])

    for profile in get_available_shells(include_default=True):
        if profile.id == shell_id:
            return profile

    # Backward-compatible fallback for old config values or direct executable names.
    resolved = shutil.which(str(shell_id)) or str(shell_id)
    if resolved:
        return _make_profile(resolved)
    return _default_profile()


def get_shell_label(shell_id=None):
    return get_shell_profile(shell_id).label


def get_shell_options(include_default=False):
    return [(profile.label, profile.id) for profile in get_available_shells(include_default=include_default)]


def shell_id_from_label(label, include_default=False):
    for profile_label, profile_id in get_shell_options(include_default=include_default):
        if profile_label == label:
            return profile_id
    return get_default_shell_id()


def shell_label_from_id(shell_id, include_default=False):
    profile = get_shell_profile(shell_id)
    for profile_label, profile_id in get_shell_options(include_default=include_default):
        if profile_id == profile.id:
            return profile_label
    return profile.label
