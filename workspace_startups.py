import uuid


DEFAULT_STARTUP_ID = "default"
DEFAULT_STARTUP_NAME = "Inicio predeterminado"


def _clean_text(value):
    return str(value or "").strip()


def default_startup_for_services(services):
    return {
        "id": DEFAULT_STARTUP_ID,
        "name": DEFAULT_STARTUP_NAME,
        "service_profiles": {
            service.id: service.default_deploy_profile_id
            for service in services or []
        },
    }


def normalize_workspace_startups(workspace_config, services):
    services = list(services or [])
    valid_service_ids = {service.id for service in services}
    raw_startups = workspace_config.get("startup_profiles") or []

    result = [default_startup_for_services(services)]
    seen_ids = {DEFAULT_STARTUP_ID}

    if isinstance(raw_startups, list):
        for index, raw_startup in enumerate(raw_startups):
            if not isinstance(raw_startup, dict):
                continue

            startup_id = _clean_text(raw_startup.get("id")) or str(uuid.uuid4())
            if startup_id in seen_ids:
                startup_id = str(uuid.uuid4())
            seen_ids.add(startup_id)

            raw_mapping = raw_startup.get("service_profiles") or {}
            mapping = {}
            if isinstance(raw_mapping, dict):
                for service_id, profile_id in raw_mapping.items():
                    service_id = _clean_text(service_id)
                    profile_id = _clean_text(profile_id)
                    if service_id in valid_service_ids and profile_id:
                        mapping[service_id] = profile_id

            result.append(
                {
                    "id": startup_id,
                    "name": _clean_text(raw_startup.get("name")) or f"Inicio {index + 1}",
                    "service_profiles": mapping,
                }
            )

    return result


def serialize_workspace_startups(startups):
    serialized = []
    for startup in startups or []:
        if startup.get("id") == DEFAULT_STARTUP_ID:
            continue

        mapping = {}
        raw_mapping = startup.get("service_profiles") or {}
        if isinstance(raw_mapping, dict):
            for service_id, profile_id in raw_mapping.items():
                service_id = _clean_text(service_id)
                profile_id = _clean_text(profile_id)
                if service_id and profile_id:
                    mapping[service_id] = profile_id

        serialized.append(
            {
                "id": _clean_text(startup.get("id")) or str(uuid.uuid4()),
                "name": _clean_text(startup.get("name")) or "Inicio",
                "service_profiles": mapping,
            }
        )

    return serialized


def get_startup_options(startups):
    return [(startup.get("name") or DEFAULT_STARTUP_NAME, startup.get("id")) for startup in startups or []]


def get_startup_by_id(startups, startup_id):
    for startup in startups or []:
        if startup.get("id") == startup_id:
            return startup
    return startups[0] if startups else None


def get_startup_label(startups, startup_id):
    startup = get_startup_by_id(startups, startup_id)
    return startup.get("name", DEFAULT_STARTUP_NAME) if startup else DEFAULT_STARTUP_NAME


def get_startup_id_from_label(startups, label):
    for startup_label, startup_id in get_startup_options(startups):
        if startup_label == label:
            return startup_id
    return startups[0].get("id") if startups else None
