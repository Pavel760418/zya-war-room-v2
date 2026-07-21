from pathlib import Path
from fastapi import APIRouter, UploadFile, File
from fastapi.responses import JSONResponse
from app.core.config import DEFAULT_EXCEL_FILE
from app.repositories.excel_repository import ExcelRepository
from app.repositories.demo_repository import DemoRepository
from app.services.metrics_service import MetricsService

router = APIRouter(prefix='/api/v1')

def build_service(mode: str = 'excel') -> MetricsService:
    if mode == 'demo':
        return MetricsService(DemoRepository().load(), mode='demo')
    return MetricsService(ExcelRepository(DEFAULT_EXCEL_FILE).load(), mode='excel')

@router.get('/filters')
def get_filters(mode: str = 'excel'):
    return JSONResponse(build_service(mode).filters())

@router.get('/dashboard')
def get_dashboard(period: str = 'month', scope: str = 'network', store: str | None = None, mode: str = 'excel'):
    selected_store = store if scope == 'store' and store else None
    return JSONResponse(build_service(mode).build_dashboard(period=period, store=selected_store).model_dump())

@router.post('/upload/excel')
async def upload_excel(file: UploadFile = File(...)):
    DEFAULT_EXCEL_FILE.write_bytes(await file.read())
    return {'status':'ok','path':str(DEFAULT_EXCEL_FILE.name)}
