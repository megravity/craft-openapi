from collections.abc import Mapping


def query_params(values: Mapping[str, str | bool | int | None]) -> dict[str, str]:
    """Only the single-value forms documented for v1; never guess array encoding."""
    return {
        key: (str(value).lower() if isinstance(value, bool) else str(value))
        for key, value in values.items()
        if value is not None
    }
