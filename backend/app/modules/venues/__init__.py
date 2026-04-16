"""Venues module — physical locations where events are held.

Separated from the events module for single-responsibility reasons:
- Venues have their own lifecycle (capacity updates, photos, floor plans planned).
- Events reference Venue via FK but do not own it.
"""
