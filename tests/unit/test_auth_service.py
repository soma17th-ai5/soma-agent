"""인증 서비스 — users upsert 동작 검증. 인메모리 SQLite로 격리."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.opensoma_client import LoginResult, WhoamiResult
from app.domain.models import Base
from app.domain.models.user import User
from app.services import auth as auth_service


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return SessionLocal()


def _login_result(role: str = "TRAINEE") -> LoginResult:
    return LoginResult(
        session_id="sid",
        soma_user_id="user@x.com",
        user_no="a" * 32,
        user_name="홍길동",
        role=role,
    )


def test_should_insertUser_when_userNoIsNew(db: Session) -> None:
    user = auth_service.upsert_user_from_login(db, _login_result())
    assert user.id is not None
    assert user.soma_user_id == "user@x.com"
    assert user.user_no == "a" * 32
    assert user.role == "TRAINEE"


def test_should_updateUserName_when_userNoExists(db: Session) -> None:
    auth_service.upsert_user_from_login(db, _login_result())
    updated = LoginResult(
        session_id="sid2",
        soma_user_id="user@x.com",
        user_no="a" * 32,
        user_name="새이름",
        role="TRAINEE",
    )
    user = auth_service.upsert_user_from_login(db, updated)
    assert user.user_name == "새이름"
    # 단일 행만 유지되는지
    assert db.query(User).count() == 1


def test_should_preserveOperatorRole_when_sidecarReturnsTrainee(db: Session) -> None:
    """운영자가 EXPERT/OPERATOR로 설정한 사용자가 sidecar 응답 'TRAINEE'로 강등되지 않음."""
    user = auth_service.upsert_user_from_login(db, _login_result())
    user.role = "OPERATOR"
    db.commit()

    auth_service.upsert_user_from_whoami(
        db,
        WhoamiResult(
            soma_user_id="user@x.com",
            user_no="a" * 32,
            user_name="홍길동",
            role="TRAINEE",
        ),
    )
    db.refresh(user)
    assert user.role == "OPERATOR"


def test_should_acceptMentorRole_when_sidecarReturnsT(db: Session) -> None:
    user = auth_service.upsert_user_from_whoami(
        db,
        WhoamiResult(
            soma_user_id="user@x.com",
            user_no="b" * 32,
            user_name="멘토",
            role="MENTOR",
        ),
    )
    assert user.role == "MENTOR"
