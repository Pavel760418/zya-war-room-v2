from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.api.routes import router

app = FastAPI(title='ZYA War Room v2', version='2.0.0')
app.include_router(router)
app.mount('/static', StaticFiles(directory='app/static'), name='static')

@app.get('/')
def root():
    return FileResponse('app/static/index.html')
