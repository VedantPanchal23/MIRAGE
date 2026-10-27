"""Pydantic schemas for public enterprise contact and demo inquiries."""

from pydantic import BaseModel, Field


class InquiryCreateRequest(BaseModel):
    """Payload for submitting an enterprise contact or sales demo inquiry."""

    name: str = Field(..., min_length=2, max_length=255, description="Full name of contact")
    email: str = Field(
        ...,
        min_length=5,
        max_length=255,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="Corporate work email address",
    )
    company: str = Field(..., min_length=2, max_length=255, description="Organization or company name")
    team_size: str = Field(default="1-10", description="Team size or headcount category")
    use_case: str = Field(default="Agent Governance", description="Primary AI assurance use case")
    message: str = Field(..., min_length=5, max_length=4000, description="Inquiry details or custom requirements")


class InquiryResponse(BaseModel):
    """Response returned upon successful receipt and persistence of inquiry."""

    id: str = Field(..., description="Unique inquiry reference ID")
    name: str
    email: str
    company: str
    team_size: str
    use_case: str
    status: str = "PENDING"
    created_at: str
    confirmation_message: str = (
        "Thank you for reaching out. An enterprise assurance engineer will review your inquiry within 4 hours."
    )
