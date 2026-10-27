# The agent's sandbox: headless FreeCAD 1.1.3 from the same layer as the verifier
# image, a virtual display so FreeCAD can render images (`xvfb-run -a freecadcmd`),
# the Deep Agents runtime and NeMo Relay for traces, and the task's mesh.
FROM condaforge/miniforge3:24.11.3-2
RUN mamba install -y -q python=3.12 freecad=1.1.3 numpy && mamba clean -a -y
RUN apt-get update -qq && apt-get install -y -qq xvfb xauth libgl1 libegl1 libxkbcommon-x11-0 \
    libxcb-cursor0 > /dev/null && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir deepagents==0.7.32 langchain-openai==1.7.2 nemo-relay==0.10.4
COPY reference.obj /app/reference.obj
WORKDIR /app
