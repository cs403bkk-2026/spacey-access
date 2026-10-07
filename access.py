def issue_access_code(cur, booking_id, eligible: bool):
    # TODO: spacey-access#2
    # eligible flag comes from Purchase — do not read bookings table here
    raise NotImplementedError


def check_in(cur, booking_id, access_code):
    # TODO: spacey-access#1
    # SP-R15: code match → not removed → not expired → within interval → available
    raise NotImplementedError


def check_out(cur, booking_id, access_code):
    # TODO: spacey-access#1
    # SP-R16: used → available (re-entry allowed)
    raise NotImplementedError


def remove_access(cur, booking_id):
    # TODO: spacey-access#1
    # SP-R12: record is never deleted, only marked removed
    # SP-R13: does not affect payments
    raise NotImplementedError


def expire_access(cur, booking_id):
    # TODO: spacey-access#1
    # SP-R17: lazy expiry — called on touch, not on a schedule
    raise NotImplementedError