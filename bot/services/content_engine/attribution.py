import re


def generate_deep_link(
    bot_username: str,
    platform: str,
    post_id: int | None = None,
    campaign: str | None = None,
) -> str:
    cleaned_bot = bot_username.lstrip("@")
    plat_short = platform.lower()
    if post_id is not None:
        payload = f"from_{plat_short}_p{post_id}"
    elif campaign:
        payload = f"from_{plat_short}_{campaign}"
    else:
        payload = f"from_{plat_short}"
    return f"https://t.me/{cleaned_bot}?start={payload}"


def parse_attribution_payload(payload: str) -> dict[str, object] | None:
    if not payload:
        return None

    # Matches: from_tg_p12, from_vk_p5, from_instagram_p8, from_threads_p10
    match = re.match(r"^from_([a-zA-Z0-9]+)_p(\d+)$", payload)
    if match:
        platform, post_id_str = match.groups()
        return {
            "platform": platform.lower(),
            "post_id": int(post_id_str),
            "campaign": None,
            "raw_payload": payload,
        }

    # Matches: from_tg, from_vk, from_instagram, from_threads
    match_plat = re.match(r"^from_([a-zA-Z0-9]+)$", payload)
    if match_plat:
        return {
            "platform": match_plat.group(1).lower(),
            "post_id": None,
            "campaign": None,
            "raw_payload": payload,
        }

    return None
