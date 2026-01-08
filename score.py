def calculate_score(
    days_past,
    lines_changed,
    comments,
    days_threshold,
    lines_changed_threshold,
    comment_threshold
):
    numerator = (
        (days_past * days_threshold)
        + (lines_changed * lines_changed_threshold)
    )

    denominator = (
        numerator
        + ((comments / comment_threshold) * 0.1 + 1)
    )

    return round(numerator / denominator, 4)