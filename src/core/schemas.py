from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ..core.models import ScamType


class ScamNumberBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    phone_number: str = Field(..., min_length=5, max_length=30)
    scam_type: ScamType = ScamType.GENERAL
    caller_name: Optional[str] = None
    notes: Optional[str] = None
    confidence: float = 1.0
    is_blocked: bool = True
    metadata_json: Optional[dict] = None

class ScamNumberCreate(ScamNumberBase):
    pass

class ScamNumberResponse(ScamNumberBase):
    id: int
    first_seen: datetime
    last_seen: datetime
    report_count: int


class ScamReportBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    phone_number: str = Field(..., min_length=5, max_length=30)
    reported_by: Optional[str] = None
    scam_type: ScamType = ScamType.GENERAL
    notes: Optional[str] = None

class ScamReportCreate(ScamReportBase):
    pass

class ScamReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    phone_number: str
    scam_type: ScamType
    reported_by: Optional[str]
    notes: Optional[str]
    is_verified: bool
    created_at: datetime


class UserBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    phone_number: str = Field(..., min_length=5, max_length=30)
    email: Optional[str] = None
    name: Optional[str] = None
    notification_enabled: bool = True

class UserCreate(UserBase):
    pass

class UserResponse(UserBase):
    id: int
    created_at: datetime


class CallRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    call_sid: str
    from_number: str
    to_number: Optional[str]
    status: str
    started_at: datetime
    ended_at: Optional[datetime]
    recording_url: Optional[str]
    transcript: Optional[str]
    scam_detected: bool
    scam_confidence: float
