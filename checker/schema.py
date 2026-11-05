"""The shape of the data the AI must return.

Every value comes with a `quote`: the exact words from the document it was
read from. Later steps check that the quote really is in the document, so the
AI cannot invent a value without being caught.

The AI only *copies* what is written. All maths (unit conversions, percentages,
totals) is done later in plain Python.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class TextValue(BaseModel):
    value: Optional[str] = None
    quote: Optional[str] = None


class NumberValue(BaseModel):
    value: Optional[float] = None
    quote: Optional[str] = None


class LineItem(BaseModel):
    item_code: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None
    quote: Optional[str] = Field(None, description="The full table row, copied exactly")


class Payment(BaseModel):
    advance_percent: Optional[float] = Field(
        None, description="Advance paid with the purchase order, as written. 0 if 'no advance'."
    )
    balance_days_min: Optional[float] = None
    balance_days_max: Optional[float] = None
    counted_from: Optional[Literal["delivery", "purchase order", "unclear"]] = None
    is_clear: Optional[bool] = Field(
        None, description="False if the payment text is confusing, repeated, contradicts itself or is open-ended"
    )
    quote: Optional[str] = None


class Delivery(BaseModel):
    number: Optional[float] = None
    unit: Optional[Literal["days", "weeks", "months"]] = None
    quote: Optional[str] = None


class Penalty(BaseModel):
    present: Optional[bool] = None
    percent: Optional[float] = None
    per: Optional[Literal["week", "day", "month", "other"]] = None
    basis_is_order_value: Optional[bool] = Field(
        None, description="True only if the text says the % is of the order value"
    )
    quote: Optional[str] = None


class Extraction(BaseModel):
    supplier_name: TextValue = TextValue()
    quotation_no: TextValue = TextValue()
    quote_date: TextValue = TextValue()
    pr_reference: TextValue = TextValue()
    items: list[LineItem] = []
    subtotal: NumberValue = NumberValue()
    vat_rate_percent: NumberValue = NumberValue()
    vat_amount: NumberValue = NumberValue()
    total: NumberValue = NumberValue()
    prices_include_vat: Optional[bool] = None
    tin: TextValue = TextValue()
    bin: TextValue = TextValue()
    payment: Payment = Payment()
    delivery: Delivery = Delivery()
    penalty: Penalty = Penalty()
    validity_days: NumberValue = NumberValue()


class Finding(BaseModel):

    check: str
    outcome: Literal["Approve", "Needs a person to check", "Reject"]
    reason: str
    quote: Optional[str] = None
    field: Optional[str] = None  


APPROVE = "Approve"
NEEDS_PERSON = "Needs a person to check"
REJECT = "Reject"
