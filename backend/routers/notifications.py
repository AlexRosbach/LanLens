from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_user
from ..database import get_db
from ..models import Notification, User
from ..schemas import MessageResponse, NotificationResponse

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    unread_only: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(Notification)
    if unread_only:
        query = query.filter(Notification.is_read == False)
    notifications = query.order_by(Notification.created_at.desc()).limit(100).all()
    return [
        NotificationResponse(
            id=n.id,
            device_id=n.device_id,
            event_type=n.event_type,
            message=n.message,
            is_read=n.is_read,
            telegram_sent=n.telegram_sent,
            created_at=n.created_at,
        )
        for n in notifications
    ]


@router.get("/unread-count")
def get_unread_count(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    count = db.query(Notification).filter(Notification.is_read == False).count()
    return {"count": count}


@router.put("/read-all", response_model=MessageResponse)
def mark_all_read(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    db.query(Notification).filter(Notification.is_read == False).update({"is_read": True})
    db.commit()
    return MessageResponse(message="All notifications marked as read")


@router.delete("/{notification_id}", response_model=MessageResponse)
def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    notif = db.query(Notification).filter(Notification.id == notification_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    db.delete(notif)
    db.commit()
    return MessageResponse(message="Notification deleted")
