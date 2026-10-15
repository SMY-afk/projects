"""Choose complete, non-overlapping reports covering exactly the requested dates."""

from datetime import timedelta


def select_complete_creator_windows(reports_by_window, window_start, window_end):
    step = timedelta(days=1)
    paths = {window_end + step: []}
    windows = sorted(
        (
            key
            for key in reports_by_window
            if window_start <= key[0] <= key[1] <= window_end
        ),
        reverse=True,
    )
    for start, end in windows:
        if start not in paths and end + step in paths:
            paths[start] = [reports_by_window[(start, end)], *paths[end + step]]
    return paths.get(window_start)
