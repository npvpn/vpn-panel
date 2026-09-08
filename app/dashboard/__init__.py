import atexit
import os
import subprocess
from pathlib import Path

from fastapi.staticfiles import StaticFiles

from app import app
from config import (
    DASHBOARD_PATH,
    DEBUG,
    VITE_BASE_API,
    resolved_subscription_templates_dir,
    subscription_statics_url,
)

base_dir = Path(__file__).parent
build_dir = base_dir / "build"
statics_dir = build_dir / "statics"


def mount_sub_statics() -> None:
    sub_dir = resolved_subscription_templates_dir()
    if sub_dir:
        app.mount(
            subscription_statics_url(),
            StaticFiles(directory=sub_dir),
            name="sub-statics",
        )


def build():
    proc = subprocess.Popen(
        ["npm", "run", "build", "--", "--outDir", build_dir, "--assetsDir", "statics"],
        env={**os.environ, "VITE_BASE_API": VITE_BASE_API},
        cwd=base_dir,
    )
    proc.wait()
    with open(build_dir / "index.html") as file:
        html = file.read()
    with open(build_dir / "404.html", "w") as file:
        file.write(html)


def run_dev():
    proc = subprocess.Popen(
        [
            "npm",
            "run",
            "dev",
            "--",
            "--host",
            "0.0.0.0",
            "--clearScreen",
            "false",
            "--base",
            os.path.join(DASHBOARD_PATH, ""),
        ],
        env={**os.environ, "VITE_BASE_API": VITE_BASE_API},
        cwd=base_dir,
    )

    atexit.register(proc.terminate)


def run_build():
    if not build_dir.is_dir():
        build()

    mount_sub_statics()
    app.mount(DASHBOARD_PATH, StaticFiles(directory=build_dir, html=True), name="dashboard")
    app.mount("/statics/", StaticFiles(directory=statics_dir, html=True), name="statics")


@app.on_event("startup")
def startup():
    if DEBUG:
        mount_sub_statics()
        run_dev()
    else:
        run_build()
