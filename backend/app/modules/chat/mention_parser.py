"""Parse @mentions from chat message bodies.

Input:  message body text + list of candidate users
Output: list of matched user_ids (deduplicated)

Matching rules:
- '@' must be preceded by whitespace or start-of-string (prevents matching
  e.g. 'email@domain.com')
- Name matching is case-insensitive
- Supports partial first-name matches: '@Omar' matches 'Omar Abdelbari El Asry'
- Supports full-name matches with hyphens or underscores replacing spaces:
  '@Manager_Cocktail_Bar' or '@Manager-Cocktail-Bar' matches 'Manager Cocktail Bar'
- Bare '@' or '@1234' is ignored
- Duplicates within one message are deduplicated
- Author never mentions themselves
"""
import re
from uuid import UUID


# Match @ followed by word chars, optional dots/dashes/underscores
# (?:^|(?<=\s)) = start of string OR preceded by whitespace (lookbehind)
MENTION_RE = re.compile(r"(?:^|(?<=\s))@([A-Za-z][A-Za-z0-9._-]{1,63})")


def parse_mentions(
    body: str,
    candidates: list[tuple[UUID, str]],
    author_id: UUID | None = None,
) -> list[UUID]:
    """Return user_ids of users mentioned in body.

    Args:
      body:        The message text
      candidates:  List of (user_id, full_name) tuples (all users in tenant)
      author_id:   The message sender — excluded from results (no self-mentions)

    Returns:
      List of UUIDs, deduplicated, preserving order of first appearance.
    """
    if not body or not candidates:
        return []

    # Find all @name tokens in the message
    raw_tokens = MENTION_RE.findall(body)
    if not raw_tokens:
        return []

    # Normalize candidate names: "Omar Abdelbari El Asry" → "omar abdelbari el asry"
    # Also create a first-name-only lookup for short mentions like @Omar
    name_to_id: dict[str, UUID] = {}
    first_name_to_ids: dict[str, list[UUID]] = {}
    for uid, full_name in candidates:
        normalized = full_name.strip().lower()
        name_to_id[normalized] = uid
        # Also index by first word
        first = normalized.split()[0] if normalized else ""
        if first:
            first_name_to_ids.setdefault(first, []).append(uid)

    matched: list[UUID] = []
    seen: set[UUID] = set()

    for token in raw_tokens:
        # Try exact full-name match (with spaces), treating . _ - as word separators
        normalized_token = token.replace(".", " ").replace("_", " ").replace("-", " ").strip().lower()
        uid: UUID | None = None

        if normalized_token in name_to_id:
            uid = name_to_id[normalized_token]
        elif normalized_token in first_name_to_ids:
            # Only match by first name if unambiguous (exactly one candidate)
            candidates_for_name = first_name_to_ids[normalized_token]
            if len(candidates_for_name) == 1:
                uid = candidates_for_name[0]

        if uid is None:
            continue
        if author_id is not None and uid == author_id:
            continue
        if uid in seen:
            continue

        matched.append(uid)
        seen.add(uid)

    return matched
