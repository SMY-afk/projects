from typing import Annotated, Any

from app.db.session import get_db
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.services.affiliate_ingest import ingest_affiliate_response

router = APIRouter(
    prefix="/affiliate",
    tags=["Affiliate"],
)


@router.post("/ingest")
def ingest_affiliate(
    payload: dict[str, Any],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, object]:
    return ingest_affiliate_response(
        db=db,
        payload=payload,
    )
