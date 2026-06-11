import uuid

from shell_profiles import get_default_shell_id


DEFAULT_PROFILE_ID = "default"
DEFAULT_PROFILE_NAME = "Predeterminado"


def new_step(command="", name=None):
    return {
        "id": str(uuid.uuid4()),
        "name": name or "Paso",
        "command": command or "",
    }


def new_profile(name=DEFAULT_PROFILE_NAME, shell=None, profile_id=None, steps=None):
    return {
        "id": profile_id or str(uuid.uuid4()),
        "name": name or DEFAULT_PROFILE_NAME,
        "shell": shell or get_default_shell_id(),
        "steps": steps or [],
    }


def _clean_text(value):
    return str(value or "").strip()


def _legacy_steps_from_config(config, keep_empty_steps=False):
    steps = []
    pre_command = _clean_text(config.get("pre_command"))
    command = _clean_text(config.get("command"))

    if pre_command or keep_empty_steps:
        steps.append(new_step(pre_command, "Paso previo"))
    if command or keep_empty_steps:
        steps.append(new_step(command, "Comando final"))

    return steps


def _normalize_step(raw_step, index, keep_empty_steps=False):
    if isinstance(raw_step, str):
        command = _clean_text(raw_step)
        name = f"Paso {index + 1}"
        step_id = str(uuid.uuid4())
    else:
        raw_step = raw_step or {}
        command = _clean_text(raw_step.get("command"))
        name = _clean_text(raw_step.get("name")) or f"Paso {index + 1}"
        step_id = _clean_text(raw_step.get("id")) or str(uuid.uuid4())

    if not command and not keep_empty_steps:
        return None

    return {
        "id": step_id,
        "name": name,
        "command": command,
    }


def normalize_service_profiles(config, keep_empty_steps=False):
    config = config or {}
    service_shell = config.get("shell") or get_default_shell_id()
    raw_profiles = config.get("deploy_profiles") or []
    profiles = []

    if isinstance(raw_profiles, list):
        for index, raw_profile in enumerate(raw_profiles):
            if not isinstance(raw_profile, dict):
                continue

            raw_steps = raw_profile.get("steps") or []
            steps = []
            for step_index, raw_step in enumerate(raw_steps):
                step = _normalize_step(raw_step, step_index, keep_empty_steps=keep_empty_steps)
                if step:
                    steps.append(step)

            if not steps and keep_empty_steps:
                steps = [
                    new_step("", "Paso previo"),
                    new_step("", "Comando final"),
                ]

            profile = {
                "id": _clean_text(raw_profile.get("id")) or str(uuid.uuid4()),
                "name": _clean_text(raw_profile.get("name")) or f"Flujo {index + 1}",
                "shell": raw_profile.get("shell") or service_shell,
                "steps": steps,
            }
            profiles.append(profile)

    if not profiles:
        profiles.append(
            new_profile(
                name=DEFAULT_PROFILE_NAME,
                shell=service_shell,
                profile_id=DEFAULT_PROFILE_ID,
                steps=_legacy_steps_from_config(config, keep_empty_steps=keep_empty_steps),
            )
        )

    default_profile_id = config.get("default_deploy_profile_id") or DEFAULT_PROFILE_ID
    profile_ids = {profile["id"] for profile in profiles}
    if default_profile_id not in profile_ids:
        default_profile_id = profiles[0]["id"]

    return profiles, default_profile_id


def serialize_profiles(profiles):
    serialized = []
    for profile in profiles or []:
        steps = []
        raw_steps = profile.get("steps") or []
        for index, step in enumerate(raw_steps):
            command = _clean_text(step.get("command") if isinstance(step, dict) else step)
            if not command:
                continue
            name = _clean_text(step.get("name") if isinstance(step, dict) else "") or (
                "Comando final" if index == len(raw_steps) - 1 else f"Paso {index + 1}"
            )
            steps.append(
                {
                    "id": (_clean_text(step.get("id")) if isinstance(step, dict) else "") or str(uuid.uuid4()),
                    "name": name,
                    "command": command,
                }
            )

        for index, step in enumerate(steps):
            step["name"] = "Comando final" if index == len(steps) - 1 else f"Paso {index + 1}"

        serialized.append(
            {
                "id": _clean_text(profile.get("id")) or str(uuid.uuid4()),
                "name": _clean_text(profile.get("name")) or DEFAULT_PROFILE_NAME,
                "shell": profile.get("shell") or get_default_shell_id(),
                "steps": steps,
            }
        )
    return serialized


def get_profile_by_id(profiles, profile_id):
    for profile in profiles or []:
        if profile.get("id") == profile_id:
            return profile
    return profiles[0] if profiles else None


def get_profile_options(profiles):
    return [(profile.get("name") or DEFAULT_PROFILE_NAME, profile.get("id")) for profile in profiles or []]


def get_profile_label(profiles, profile_id):
    profile = get_profile_by_id(profiles, profile_id)
    return profile.get("name", DEFAULT_PROFILE_NAME) if profile else DEFAULT_PROFILE_NAME


def get_profile_id_from_label(profiles, label):
    for profile_label, profile_id in get_profile_options(profiles):
        if profile_label == label:
            return profile_id
    return profiles[0].get("id") if profiles else None


def legacy_fields_from_profile(profile):
    steps = [step for step in (profile or {}).get("steps", []) if _clean_text(step.get("command"))]
    if not steps:
        return "", ""

    previous = " && ".join(step["command"] for step in steps[:-1])
    return previous, steps[-1]["command"]
