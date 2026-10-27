# Verifier image: FreeCAD 1.1.3 (same version as the host) to open the saved
# document, re-run the dimension check and recompute IoU offline.
FROM condaforge/miniforge3:24.11.3-2
RUN mamba install -y -q python=3.12 freecad=1.1.3 numpy && mamba clean -a -y
COPY . /tests/
