from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import Segment, User
from ..schemas import MessageResponse, SegmentCreate, SegmentResponse, SegmentUpdate

router = APIRouter(prefix="/api/segments", tags=["segments"])


@router.get("", response_model=List[SegmentResponse])
def list_segments(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return db.query(Segment).order_by(Segment.name).all()


@router.post("", response_model=SegmentResponse, status_code=201)
def create_segment(
    data: SegmentCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    segment = Segment(**data.model_dump())
    db.add(segment)
    db.commit()
    db.refresh(segment)
    return segment


@router.put("/{segment_id}", response_model=SegmentResponse)
def update_segment(
    segment_id: int,
    data: SegmentUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(segment, field, value)
    db.commit()
    db.refresh(segment)
    return segment


@router.delete("/{segment_id}", response_model=MessageResponse)
def delete_segment(
    segment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    segment = db.query(Segment).filter(Segment.id == segment_id).first()
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
    db.delete(segment)
    db.commit()
    return MessageResponse(message="Segment deleted")
