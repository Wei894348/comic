from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .schemas import DownloadJobStatus, DownloadRequest, NetworkSettings, SearchResponse
from .services import (
    default_network_settings,
    download_config,
    download_jobs,
    get_album_detail,
    get_cached_albums,
    schema_to_album,
    search_albums,
)


app = FastAPI(title="Comic18 Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True, "backend": "fastapi"}


@app.get("/settings/default", response_model=NetworkSettings)
def default_settings():
    return default_network_settings()


@app.get("/albums/rank", response_model=SearchResponse)
def rank_albums(
    rank_type: str = Query("day", pattern="^(day|week|month)$"),
    page: int = Query(1, ge=1),
    include_detail: bool = False,
):
    albums = search_albums(rank_type=rank_type, page=page, include_detail=include_detail)
    return SearchResponse(albums=albums, count=len(albums))


@app.get("/albums/search", response_model=SearchResponse)
def search(
    query: str,
    page: int = Query(1, ge=1),
    include_detail: bool = False,
):
    albums = search_albums(query=query, page=page, include_detail=include_detail)
    return SearchResponse(albums=albums, count=len(albums))


@app.get("/albums/{album_id}")
def album_detail(album_id: str):
    return get_album_detail(album_id)


@app.get("/albums/{album_id}/chapters")
def album_chapters(album_id: str):
    album = get_album_detail(album_id)
    return {"album_id": album.album_id, "chapters": album.chapters, "count": len(album.chapters)}


@app.get("/cache/albums", response_model=SearchResponse)
def cached_albums(limit: int = Query(120, ge=1, le=1000)):
    albums = get_cached_albums(limit)
    return SearchResponse(albums=albums, count=len(albums))


@app.post("/downloads", response_model=DownloadJobStatus)
def start_download(request: DownloadRequest):
    if not request.albums:
        raise HTTPException(status_code=400, detail="albums 不能为空")
    albums = [schema_to_album(album) for album in request.albums]
    return download_jobs.start(albums, download_config(request.settings))


@app.get("/downloads/{job_id}", response_model=DownloadJobStatus)
def download_status(job_id: str):
    status = download_jobs.get(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="下载任务不存在")
    return status


@app.post("/downloads/{job_id}/cancel", response_model=DownloadJobStatus)
def cancel_download(job_id: str):
    status = download_jobs.cancel(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="下载任务不存在")
    return status


def create_app() -> FastAPI:
    return app
