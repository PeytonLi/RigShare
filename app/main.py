from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="RigShare")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "rigshare"}


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>RigShare</title>
  </head>
  <body>
    <h1>RigShare</h1>
    <p>Text the number. Borrow a charger. Pay a hold. Bring it back.</p>
    <p><a href="/health">health</a></p>
  </body>
</html>
"""
