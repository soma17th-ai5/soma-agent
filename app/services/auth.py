"""인증 서비스. sidecar 위임 + users upsert.

호출 흐름:
  api.auth → services.auth.login(...) → adapters.opensoma_client.login(...)
                                      → users 테이블 upsert
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.opensoma_client import LoginResult, OpenSomaClient, WhoamiResult
from app.domain.models.user import User


def login(db: Session, client: OpenSomaClient, username: str, password: str) -> LoginResult:
    """sidecar로 로그인 위임 후 users 행 upsert. session_id 포함 결과 반환.

    실패는 OpenSomaClientError로 전파 (api 레이어에서 HTTP 매핑).
    """
    result = client.login(username, password)
    upsert_user_from_login(db, result)
    return result


def upsert_user_from_login(db: Session, login_result: LoginResult) -> User:
    return _upsert(
        db,
        soma_user_id=login_result.soma_user_id,
        user_no=login_result.user_no,
        user_name=login_result.user_name,
        role=login_result.role,
    )


def upsert_user_from_whoami(db: Session, whoami: WhoamiResult) -> User:
    return _upsert(
        db,
        soma_user_id=whoami.soma_user_id,
        user_no=whoami.user_no,
        user_name=whoami.user_name,
        role=whoami.role,
    )


def _upsert(
    db: Session,
    *,
    soma_user_id: str,
    user_no: str,
    user_name: str | None,
    role: str,
) -> User:
    stmt = select(User).where(User.user_no == user_no)
    user = db.execute(stmt).scalar_one_or_none()
    if user is None:
        user = User(
            soma_user_id=soma_user_id,
            user_no=user_no,
            user_name=user_name,
            role=role,
        )
        db.add(user)
    else:
        user.soma_user_id = soma_user_id
        user.user_name = user_name
        # 운영자가 EXPERT/OPERATOR로 부여한 사용자는 sidecar의 'TRAINEE'/'MENTOR'로
        # 강등되지 않게 보호. C/T → TRAINEE/MENTOR 매핑만 받아들임.
        if user.role in ("TRAINEE", "MENTOR"):
            user.role = role
    db.commit()
    db.refresh(user)
    return user
