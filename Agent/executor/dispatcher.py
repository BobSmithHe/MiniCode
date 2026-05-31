"""Tool dispatcher helpers — inject background results into messages."""

from .executor import collect_background_results


def build_user_content(results: list[dict]) -> list[dict]:
    """Merge completed background notifications with tool results."""
    content = []
    for note in collect_background_results():
        content.append({"type": "text", "text": note})
    content.extend(results)
    return content


def inject_background_notifications(messages: list):
    notes = collect_background_results()
    if notes:
        messages.append({"role": "user", "content": [
            {"type": "text", "text": note} for note in notes]})
