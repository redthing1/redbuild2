#!/usr/bin/env python3

"""
redbuild
"""

import toml
import sh
import sys
import os
import typer
import multiprocessing
import psutil
from loguru import logger
from typing import List, Optional

from . import __version__
from .engine import (
    ContainerEngine,
    detect_container_engine,
    get_container_engine_command,
)
from .util import get_builder_image_name, parse_secondary_args
from .res import DEFAULT_BUILDENV_DOCKERFILE

APP_NAME = "redbuild"
app = typer.Typer(
    name=APP_NAME,
    help=f"{APP_NAME}: a tool for easy magic containerized builds",
    no_args_is_help=True,
)

DEFAULT_DOCKERFILE = (
    "build.docker"  # filename of default dockerfile for build environment
)
VOLUME_OPTS = ":z"  # bind mount volume options


@app.command()
def info():
    app_info_logo = f"{APP_NAME} v{__version__}"
    print(app_info_logo)
    print("- " * (len(app_info_logo) // 2 + 1))

    # show info about host
    print("Host information:")
    host_os = sys.platform
    host_arch = sys.maxsize > 2**32 and "64bit" or "32bit"
    host_cores = multiprocessing.cpu_count()
    host_memory = int(psutil.virtual_memory().total / 1024**2)
    print(f"  Host OS: {host_os}")
    print(f"  Host architecture: {host_arch}")
    print(f"  Host cores: {host_cores}")
    print(f"  Host memory: {host_memory} MB")

    # show info about container engine
    container_engine = detect_container_engine()
    print(f"Container engine: {container_engine}")
    ctr_engine = get_container_engine_command(container_engine)
    print(f"  Version: {ctr_engine('--version')}", end="")


@app.command(help="Build a container image for the build environment")
def image(
    dockerfile: str = typer.Option(
        DEFAULT_DOCKERFILE,
        "--dockerfile",
        "-f",
        help="Dockerfile to use for defining the build environment",
    ),
    cwd: str = typer.Option(
        ".", "--cwd", "-C", help="Directory to use as the build context"
    ),
):
    # 0. get container engine
    ctr_engine = get_container_engine_command(detect_container_engine())
    # 1. get name for builder image
    builder_image_name = get_builder_image_name(cwd)

    # full path to dockerfile
    dockerfile = os.path.join(cwd, dockerfile)

    # 2. build builder image
    # ensure dockerfile exists
    if not os.path.isfile(dockerfile):
        print(
            f"Dockerfile [{dockerfile}] not found. Create it or pass a specific path with -f."
        )
        raise typer.Exit(1)

    # $CONTAINER_ENGINE build -t $BUILDER_TAG $CBUILD_ARGS -f $DOCKERFILE | sed 's/^/  /'
    print(f"Building builder image [{builder_image_name}] in context [{cwd}]:")
    build_cmd = ctr_engine.bake(
        "build",
        cwd,
        # podman build args
        t=builder_image_name,
        f=dockerfile,
        # _fg=True,
        # output formatting
        _out=lambda line: print(f"  {line}", end=""),
        _err=lambda line: print(f"  {line}", end=""),
    )

    logger.debug(f"Running command: {build_cmd}")
    build_proc = build_cmd()


@app.command(help="Run a build script in the build environment")
def build(
    dockerfile: str = typer.Option(
        DEFAULT_DOCKERFILE,
        "--dockerfile",
        "-f",
        help="Dockerfile to use for defining the build environment",
    ),
    buildscript: str = typer.Option(
        "build.sh", "--buildscript", "-s", help="Build script to run in the container"
    ),
    cwd: str = typer.Option(
        ".", "--cwd", "-C", help="Directory to use as the build context"
    ),
    crun_args=typer.Option(
        "",
        "--crun-args",
        "-R",
        help="Additional arguments to pass to container engine",
    ),
    build_args=typer.Option(
        "",
        "--build-args",
        "-B",
        help="Additional arguments to pass to build script",
    ),
):
    # 0. get container engine
    ctr_engine = get_container_engine_command(detect_container_engine())

    # 1. get name for builder image
    builder_image_name = get_builder_image_name(cwd)

    # 2. build builder image
    image(dockerfile=dockerfile, cwd=cwd)

    # 3. run build
    buildscript_path = os.path.join(cwd, buildscript)
    # ensure buildscript exists
    if not os.path.isfile(buildscript_path):
        print(
            f"Build script [{buildscript_path}] not found. Create it or pass a specific path with -s."
        )
        raise typer.Exit(1)
    # $CONTAINER_ENGINE run --rm -it -v $(pwd):/prj $CRUN_ARGS $BUILDER_TAG /bin/bash -l -c "cd /prj && $BUILDSCRIPT $ARGS" | sed 's/^/  /'
    print(
        f"Running build in [{builder_image_name}] with buildscript [{buildscript}] in context [{cwd}]:"
    )
    run_cmd_args = [
        "run",
        # podman run args
        "--rm",
        # "-it",
        "-v",
        f"{cwd}:/prj{VOLUME_OPTS}",
        *parse_secondary_args(crun_args),
    ]
    run_cmd = ctr_engine.bake(
        *run_cmd_args,
        # _fg=True,
        # output formatting
        _out=lambda line: print(f"  {line}", end=""),
        _err=lambda line: print(f"  {line}", end=""),
    )

    relative_buildscript = f"./{buildscript}"
    logger.debug(f"Running command: {run_cmd}")
    run_proc = run_cmd(
        builder_image_name,
        "/bin/bash",
        "-l",
        "-c",
        f"cd /prj && {relative_buildscript} {build_args}",
    )


@app.command(help="Run a shell in the build environment")
def shell(
    dockerfile: str = typer.Option(
        DEFAULT_DOCKERFILE,
        "--dockerfile",
        "-f",
        help="Dockerfile to use for defining the build environment",
    ),
    cwd: str = typer.Option(
        ".", "--cwd", "-C", help="Directory to use as the build context"
    ),
    crun_args=typer.Option(
        "",
        "--crun-args",
        "-R",
        help="Additional arguments to pass to container engine",
    ),
    shell_args=typer.Option(
        "",
        "--shell-args",
        "-A",
        help="Additional arguments to pass to shell",
    ),
):
    # 0. get container engine
    ctr_engine = get_container_engine_command(detect_container_engine())

    # 1. get name for builder image
    builder_image_name = get_builder_image_name(cwd)

    # 2. build builder image
    image(dockerfile=dockerfile, cwd=cwd)

    # 3. run an interactive shell with the build environment
    print(f"Running interactive shell in [{builder_image_name}] in context [{cwd}]:")
    run_cmd_args = [
        "run",
        # podman run args
        "--rm",
        "-it",
        "-v",
        f"{cwd}:/prj{VOLUME_OPTS}",
        *parse_secondary_args(crun_args),
    ]
    run_cmd = ctr_engine.bake(
        *run_cmd_args,
    )

    logger.debug(f"Running command: {run_cmd}")
    run_proc = run_cmd(
        builder_image_name,
        "/bin/bash",
        "-l",
        *parse_secondary_args(shell_args),
        _fg=True,
    )


@app.command(help="Initialize a build environment")
def init(
    dockerfile: str = typer.Option(
        DEFAULT_DOCKERFILE,
        "--dockerfile",
        "-f",
        help="Dockerfile to use for defining the build environment",
    ),
    cwd: str = typer.Option(
        ".", "--cwd", "-C", help="Directory to use as the build context"
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Force initialization even if Dockerfile exists"
    ),
):
    # first, ensure that no build environment already exists
    dockerfile_path = os.path.join(cwd, dockerfile)
    if os.path.exists(dockerfile_path) and not force:
        # logger.error(f"{dockerfile} already exists in {cwd}")
        print(
            f"Failed to initialize build environment dockerfile: [{dockerfile}] already exists in [{cwd}]."
        )
        raise typer.Exit(1)

    # write out a default Dockerfile
    with open(dockerfile_path, "w") as f:
        f.write(DEFAULT_BUILDENV_DOCKERFILE)

    print(f"Initialized build environment dockerfile: Created [{dockerfile_path}].")


def version_callback(value: bool):
    if value:
        print(__version__)
        raise typer.Exit()


@app.callback()
def app_callback(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    version: Optional[bool] = typer.Option(
        None, "--version", "-V", callback=version_callback
    ),
):
    # loguru setup
    logger.remove()
    if verbose:
        logger.add(sys.stderr, level="DEBUG")
    else:
        logger.add(sys.stderr, level="INFO")


def main():
    app()
