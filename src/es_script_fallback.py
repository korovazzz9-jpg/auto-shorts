"""Bounded ES replacement after a rejected script and its repair."""


def choose_fallback(pop_next, generate, review, queue_limit=3):
    """Prefer already paid queue entries; generate one ordinary fact only if needed."""
    for index in range(queue_limit):
        candidate = pop_next()
        if candidate is None:
            break
        approved, reason = review(candidate)
        if approved:
            print(f"  ES fact review: queued fallback approved ({index + 1}/{queue_limit}).")
            return candidate
        print(f"  ES fact review: queued fallback rejected ({index + 1}/{queue_limit}): {reason}")

    print("  ES fact review: no approved queue backup; generating one ordinary fact.")
    candidate = generate()
    approved, reason = review(candidate)
    if approved:
        print("  ES fact review: live fallback approved.")
        return candidate
    raise RuntimeError(f"ES backup script failed independent fact review: {reason}")
