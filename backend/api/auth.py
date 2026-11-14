"""
API routes — optional accounts.
Login is never required. A signed-in user's analyses are saved to their history so they can reopen them.

POST   /api/auth/signup            {email, password, name?} -> {token, user}
POST   /api/auth/login             {email, password}        -> {token, user}
POST   /api/auth/logout
GET    /api/auth/me
GET    /api/auth/history           past analyses of the signed-in user
POST   /api/auth/history           {analysis_id} save an analysis to the history
GET    /api/auth/history/{id}/jd   job description text of a saved analysis
DELETE /api/auth/history/{id}
"""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.db_models import Analysis, AuthSession, JobDescription, Resume, User, UserAnalysis

router = APIRouter(prefix="/api/auth", tags=["auth"])

ITERATIONS = 260_000
SESSION_DAYS = 30
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), ITERATIONS).hex()
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest}"


def _check_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
    except ValueError:
        return False
    test = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iters)).hex()
    return hmac.compare_digest(test, digest)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _public(user: User) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name}


def _issue(db: Session, user: User) -> dict:
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(token_hash=_token_hash(token), user_id=user.id,
                       expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)))
    db.commit()
    return {"token": token, "user": _public(user)}


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def optional_user(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> Optional[User]:
    token = _bearer(authorization)
    if not token:
        return None
    s = db.query(AuthSession).filter(AuthSession.token_hash == _token_hash(token)).first()
    if not s:
        return None
    exp = s.expires_at if s.expires_at.tzinfo else s.expires_at.replace(tzinfo=timezone.utc)
    if exp < datetime.now(timezone.utc):
        db.delete(s)
        db.commit()
        return None
    return db.query(User).filter(User.id == s.user_id).first()


def require_user(user: Optional[User] = Depends(optional_user)) -> User:
    if not user:
        raise HTTPException(401, "Sign in to use this")
    return user


class SignupRequest(BaseModel):
    email: str
    password: str
    name: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class SaveRequest(BaseModel):
    analysis_id: str


@router.post("/signup")
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    email = req.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(422, "Enter a valid email address")
    if len(req.password) < 8:
        raise HTTPException(422, "Use a password of at least 8 characters")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    user = User(email=email, name=(req.name or "").strip() or None, password_hash=_hash_password(req.password))
    db.add(user)
    db.commit()
    return _issue(db, user)


@router.post("/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email.strip().lower()).first()
    if not user or not _check_password(req.password, user.password_hash):
        raise HTTPException(401, "Email or password is incorrect")
    return _issue(db, user)


@router.post("/logout")
def logout(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    token = _bearer(authorization)
    if token:
        db.query(AuthSession).filter(AuthSession.token_hash == _token_hash(token)).delete()
        db.commit()
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(require_user)):
    return _public(user)


@router.post("/history")
def save_history(req: SaveRequest, user: User = Depends(require_user), db: Session = Depends(get_db)):
    a = db.query(Analysis).filter(Analysis.id == req.analysis_id).first()
    if not a:
        raise HTTPException(404, "Analysis not found")
    existing = db.query(UserAnalysis).filter(UserAnalysis.user_id == user.id, UserAnalysis.analysis_id == a.id).first()
    if existing:
        return {"id": existing.id}
    row = UserAnalysis(user_id=user.id, analysis_id=a.id, resume_id=a.resume_id)
    db.add(row)
    db.commit()
    return {"id": row.id}


@router.get("/history")
def list_history(user: User = Depends(require_user), db: Session = Depends(get_db)):
    rows = (db.query(UserAnalysis, Analysis, Resume)
            .join(Analysis, Analysis.id == UserAnalysis.analysis_id)
            .join(Resume, Resume.id == UserAnalysis.resume_id)
            .filter(UserAnalysis.user_id == user.id)
            .order_by(UserAnalysis.created_at.desc()).all())
    out = []
    for ua, a, r in rows:
        jd = db.query(JobDescription).filter(JobDescription.id == a.jd_id).first() if a.jd_id else None
        jd_data = (jd.structured_json or {}) if jd else {}
        out.append({
            "id": ua.id, "analysis_id": a.id, "resume_id": r.id, "jd_id": a.jd_id,
            "filename": r.filename, "file_type": r.file_type,
            "name": ((r.structured_json or {}).get("contact") or {}).get("name"),
            "role": jd_data.get("title") or a.target_role, "company": jd_data.get("company"),
            "ats_score": a.ats_score, "readability_score": a.readability_score, "match_score": a.match_score,
            "created_at": ua.created_at.isoformat() if ua.created_at else None,
        })
    return {"items": out}


@router.get("/history/{item_id}/jd")
def history_jd(item_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    ua = db.query(UserAnalysis).filter(UserAnalysis.id == item_id, UserAnalysis.user_id == user.id).first()
    if not ua:
        raise HTTPException(404, "Not in your history")
    a = db.query(Analysis).filter(Analysis.id == ua.analysis_id).first()
    jd = db.query(JobDescription).filter(JobDescription.id == a.jd_id).first() if a and a.jd_id else None
    return {"jd_text": jd.raw_text if jd else ""}


@router.delete("/history/{item_id}")
def delete_history(item_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    n = db.query(UserAnalysis).filter(UserAnalysis.id == item_id, UserAnalysis.user_id == user.id).delete()
    db.commit()
    if not n:
        raise HTTPException(404, "Not in your history")
    return {"ok": True}
