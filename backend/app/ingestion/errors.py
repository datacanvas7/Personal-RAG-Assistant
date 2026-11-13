class IngestionError(Exception):
    """A document cannot be processed, and trying again will not help.

    The message is shown to the user, so it must be actionable and must not contain
    paths, library names or stack details.
    """
