# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Root Typer app for the `hep` CLI — registers one subgroup per framework family."""

from __future__ import annotations

import typer

from hep.cli.langchain import app as langchain_app

app = typer.Typer(name="hep", help="Harness Engineering Playground — automated harness profile improvement.")
app.add_typer(langchain_app)


if __name__ == "__main__":
    app()
