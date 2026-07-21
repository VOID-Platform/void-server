import os
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db, engine, Base
from models import IncidentModel, ReportModel

# Initialize database tables if not existing
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="VOID Server FastAPI Service",
    description="FastAPI microservice for AI Agent telemetry, risk analysis & reports",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "service": "fastapi-api", "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection error: {str(e)}")

@app.get("/api/incidents")
def list_incidents(db: Session = Depends(get_db)):
    incidents = db.query(IncidentModel).all()
    return {"count": len(incidents), "data": incidents}

@app.get("/api/reports")
def list_reports(db: Session = Depends(get_db)):
    reports = db.query(ReportModel).all()
    return {"count": len(reports), "data": reports}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("FASTAPI_PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
