# The agent's sandbox: headless FreeCAD 1.1.3 from the same layer as the verifier
# image, the Deep Agents runtime and NeMo Relay for traces, and the task's mesh.
FROM condaforge/miniforge3:24.11.3-2
RUN mamba install -y -q python=3.12 freecad=1.1.3 numpy && mamba clean -a -y
RUN pip install --no-cache-dir deepagents==0.7.25 langchain-openai==1.7.2 nemo-relay==0.7.3
COPY reference_part_2.obj /app/reference_part_2.obj
WORKDIR /app
