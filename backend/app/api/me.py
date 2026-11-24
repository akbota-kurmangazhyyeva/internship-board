"""The signed-in student: profile, saved vacancies, consent, feedback, account deletion (FR-14, FR-15, FR-21, FR-22)."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import delete, select

from app.api.deps import CurrentUser, SessionDep
from app.models import CanonicalVacancy, Interaction, SavedVacancy, StudentProfile
from app.schemas import (
    ConsentIn,
    InteractionIn,
    InteractionOut,
    ProfileIn,
    ProfileOut,
    SavedOut,
    SaveIn,
    UserOut,
)
from app.services.vacancies import build_cards

router = APIRouter(prefix="/me", tags=["me"])

# Explicit feedback is a feature (it hides cards), so it is stored regardless of analytics consent.
# Behavioural signals are analytics and need consent (FR-15, NFR-10, DR-01).
FEEDBACK_KINDS = {"dismiss", "not_relevant"}
BEHAVIOURAL_KINDS = {"view", "click_apply"}


@router.get("", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(user: CurrentUser, session: SessionDep) -> Response:
    """Deletes the account and all personal data: profile, saved list, interactions (FR-15)."""
    session.delete(user)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/consent", response_model=UserOut)
def set_consent(body: ConsentIn, user: CurrentUser, session: SessionDep) -> UserOut:
    user.tracking_consent = body.tracking
    user.consent_updated_at = datetime.now(UTC)
    if not body.tracking:  # withdrawing consent also erases what was collected under it
        session.execute(
            delete(Interaction).where(Interaction.user_id == user.id, Interaction.kind.in_(BEHAVIOURAL_KINDS))
        )
    session.commit()
    return UserOut.model_validate(user)


# --------------------------------------------------------------------------- profile


@router.get("/profile", response_model=ProfileOut)
def get_profile(user: CurrentUser) -> ProfileOut:
    if user.profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no profile yet")
    return ProfileOut.model_validate(user.profile)


@router.put("/profile", response_model=ProfileOut)
def put_profile(body: ProfileIn, user: CurrentUser, session: SessionDep) -> ProfileOut:
    profile = user.profile or StudentProfile(user_id=user.id)
    for key, value in body.model_dump().items():
        setattr(profile, key, value)
    if user.profile is None:
        session.add(profile)
        user.profile = profile
    session.commit()
    session.refresh(profile)
    return ProfileOut.model_validate(profile)


# --------------------------------------------------------------------------- saved vacancies


@router.get("/saved", response_model=list[SavedOut])
def list_saved(user: CurrentUser, session: SessionDep) -> list[SavedOut]:
    """Ordered by deadline, soonest first; unknown deadlines last (FR-22). Expired ones stay visible, flagged."""
    rows = session.execute(
        select(SavedVacancy, CanonicalVacancy)
        .join(CanonicalVacancy, CanonicalVacancy.id == SavedVacancy.vacancy_id)
        .where(SavedVacancy.user_id == user.id, CanonicalVacancy.status != "hidden")
        .order_by(CanonicalVacancy.deadline.asc().nulls_last(), SavedVacancy.created_at.desc())
    ).all()
    cards = build_cards(session, [v for _, v in rows], user)
    return [
        SavedOut(vacancy=card, saved_at=s.created_at, remind=s.remind) for (s, _), card in zip(rows, cards, strict=True)
    ]


@router.put("/saved/{vacancy_id}", response_model=SavedOut)
def save_vacancy(vacancy_id: int, user: CurrentUser, session: SessionDep, body: SaveIn | None = None) -> SavedOut:
    vacancy = session.get(CanonicalVacancy, vacancy_id)
    if vacancy is None or vacancy.status == "hidden":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "vacancy not found")
    saved = session.get(SavedVacancy, (user.id, vacancy_id))
    if saved is None:
        saved = SavedVacancy(user_id=user.id, vacancy_id=vacancy_id)
        session.add(saved)
    saved.remind = (body or SaveIn()).remind
    session.commit()
    session.refresh(saved)
    card = build_cards(session, [vacancy], user)[0]
    return SavedOut(vacancy=card, saved_at=saved.created_at, remind=saved.remind)


@router.delete("/saved/{vacancy_id}", status_code=status.HTTP_204_NO_CONTENT)
def unsave_vacancy(vacancy_id: int, user: CurrentUser, session: SessionDep) -> Response:
    session.execute(delete(SavedVacancy).where(SavedVacancy.user_id == user.id, SavedVacancy.vacancy_id == vacancy_id))
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- feedback / interactions


@router.post("/interactions", response_model=InteractionOut)
def record_interaction(body: InteractionIn, user: CurrentUser, session: SessionDep) -> InteractionOut:
    if session.get(CanonicalVacancy, body.vacancy_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "vacancy not found")
    if body.kind in BEHAVIOURAL_KINDS and not user.tracking_consent:
        return InteractionOut(recorded=False, reason="no_consent")
    session.add(Interaction(user_id=user.id, vacancy_id=body.vacancy_id, kind=body.kind))
    session.commit()
    return InteractionOut(recorded=True)
