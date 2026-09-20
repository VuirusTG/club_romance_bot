def clamp_page(page: int, total_pages: int) -> int:
    return max(1, min(page, max(1, total_pages)))

