from pathlib import Path
from time import perf_counter
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.db import metrics, initialize, connection
from app.api import router


def create_app():
    app=FastAPI(title='Запись на приём — evgenii_nevokshenov',version='1.0.0')

    @app.middleware('http')
    async def timing(request,call_next):
        state={'sql_ms':0.0,'queries':0}
        token=metrics.set(state)
        start=perf_counter()
        try:
            response=await call_next(request)
            elapsed=(perf_counter()-start)*1000
            response.headers['Server-Timing']=f"app;dur={elapsed:.3f}, sql;dur={state['sql_ms']:.3f}, queries;desc=\"{state['queries']}\""
            response.headers['Cache-Control']='no-store'
            return response
        finally: metrics.reset(token)

    @app.get('/health')
    def health():
        with connection() as db: db.execute('SELECT 1')
        return {'ok':True,'project':'evgenii_nevokshenov'}

    app.include_router(router)
    static=Path(__file__).with_name('static')
    app.mount('/',StaticFiles(directory=static,html=True),name='static')
    return app

app=create_app()

if __name__=='__main__':
    import uvicorn
    initialize()
    from scripts.seed import seed_dataset
    with connection() as db:
        if db.execute('SELECT count(*) AS n FROM users').fetchone()['n']==0:
            seed_dataset(db,'small')
    uvicorn.run(app,host='0.0.0.0',port=8083,access_log=False)
