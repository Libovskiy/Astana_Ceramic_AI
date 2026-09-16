"""
Переписка между людьми: личные диалоги и группы.

Доступ есть у всех, кто вошёл в систему: договориться о подмене или
позвать электрика нужно любому. Ограничение одно — читать переписку
может только её участник, это проверяется на каждом запросе.

Логика и объяснения решений — в backend/services/team_chat_service.py.
"""

from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel

from backend.services.auth_service import get_user_by_session
from backend.services import team_chat_service as svc

router = APIRouter(prefix="/api/messenger", tags=["messenger"])


def current_user(session_token: str | None = Cookie(default=None)):
    user = get_user_by_session(session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")
    return user


def _handle(func, *args, **kwargs):
    """
    ValueError — человек что-то не так ввёл (400).
    PermissionError — полез в чужую переписку (403).
    Без этого и то и другое превращалось бы в 500.
    """
    try:
        return func(*args, **kwargs)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class DmPayload(BaseModel):
    user_id: int


class GroupPayload(BaseModel):
    title: str
    member_ids: list[int] = []


class MessagePayload(BaseModel):
    text: str


class MembersPayload(BaseModel):
    user_ids: list[int]


class TitlePayload(BaseModel):
    title: str


class ReadPayload(BaseModel):
    message_id: int | None = None


@router.get("/contacts")
def contacts(user: dict = Depends(current_user)):
    return {"success": True, "contacts": svc.list_contacts(user["id"])}


@router.get("/conversations")
def conversations(user: dict = Depends(current_user)):
    return {"success": True, "conversations": svc.list_conversations(user["id"])}


@router.get("/unread")
def unread(user: dict = Depends(current_user)):
    """Для значка в меню. Зовётся часто, поэтому считает одним запросом."""
    return {"success": True, "unread": svc.unread_total(user["id"])}


@router.post("/conversations/dm")
def open_dm(payload: DmPayload, user: dict = Depends(current_user)):
    conversation_id = _handle(svc.open_dm, user["id"], payload.user_id)
    return {"success": True, "conversation_id": conversation_id}


@router.post("/conversations/group")
def create_group(payload: GroupPayload, user: dict = Depends(current_user)):
    conversation_id = _handle(svc.create_group, user["id"], payload.title, payload.member_ids)
    return {"success": True, "conversation_id": conversation_id}


@router.get("/conversations/{conversation_id}/messages")
def messages(conversation_id: int, after_id: int = 0, user: dict = Depends(current_user)):
    data = _handle(svc.get_messages, conversation_id, user["id"], after_id)
    return {"success": True, **data}


@router.post("/conversations/{conversation_id}/messages")
def send(conversation_id: int, payload: MessagePayload, user: dict = Depends(current_user)):
    message = _handle(svc.send_message, conversation_id, user["id"], payload.text)
    return {"success": True, "message": message}


@router.post("/conversations/{conversation_id}/read")
def read(conversation_id: int, payload: ReadPayload, user: dict = Depends(current_user)):
    last = _handle(svc.mark_read, conversation_id, user["id"], payload.message_id)
    return {"success": True, "last_read_message_id": last}


@router.delete("/messages/{message_id}")
def delete_message(message_id: int, user: dict = Depends(current_user)):
    _handle(svc.delete_message, message_id, user["id"])
    return {"success": True}


@router.post("/conversations/{conversation_id}/members")
def add_members(conversation_id: int, payload: MembersPayload, user: dict = Depends(current_user)):
    members = _handle(svc.add_members, conversation_id, user["id"], payload.user_ids)
    return {"success": True, "members": members}


@router.delete("/conversations/{conversation_id}/members/{user_id}")
def remove_member(conversation_id: int, user_id: int, user: dict = Depends(current_user)):
    members = _handle(svc.remove_member, conversation_id, user["id"], user_id)
    return {"success": True, "members": members}


@router.put("/conversations/{conversation_id}/title")
def rename(conversation_id: int, payload: TitlePayload, user: dict = Depends(current_user)):
    title = _handle(svc.rename_group, conversation_id, user["id"], payload.title)
    return {"success": True, "title": title}


@router.post("/conversations/{conversation_id}/leave")
def leave(conversation_id: int, user: dict = Depends(current_user)):
    _handle(svc.leave, conversation_id, user["id"])
    return {"success": True}
