from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import auth, me, meta, vacancies
from app.api.deps import SessionDep
from app.config import get_settings

app = FastAPI(
    title="Internship Board API",
    version="0.1.0",
    description="Search, filter and personalised ranking of internships in Kazakhstan.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)

for router in (auth.router, vacancies.router, me.router, meta.router):
    app.include_router(router, prefix="/api/v1")


@app.get("/health", tags=["meta"])
def health(session: SessionDep) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ok"}
