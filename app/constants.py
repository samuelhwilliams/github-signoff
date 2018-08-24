import enum


APP_NAME = "product-signoff"
AWAITING_PRODUCT_REVIEW = "Awaiting product signoff"
TICKET_APPROVED_BY = "Product signoff has been received"


class StatusEnum(enum.Enum):
    """
    Matches status options from GitHub status feature: https://developer.github.com/v3/repos/statuses/#create-a-status

    PENDING -> Trello ticket for this PR still needs product review.
    SUCCESS -> Trello ticket for this PR has been moved into 'Product accepted' column.
    """

    PENDING = "pending"
    SUCCESS = "success"
